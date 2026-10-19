"""Garde-fous du schéma que l'autogénération Alembic ne voit pas (CHECK, prédicats d'index
partiels, clés primaires et composites), déclencheurs, verrou et retour arrière."""

import threading
from collections.abc import Callable
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from test_migrations import (
    connect,
    seed_execution,
    seed_plan,
    seed_project,
    table_names,
)

from foreman.config.env import ENV_ALLOW_DESTRUCTIVE_DOWNGRADE
from foreman.infra.db import tables as t
from foreman.infra.db.migrate import MIGRATION_LOCK_KEY, downgrade, upgrade_head


@pytest.fixture
def migrated(blank_database_url: str) -> str:
    upgrade_head(blank_database_url)
    return blank_database_url


# --- La base migrée est identique à celle que construit tables.py (comparée par PostgreSQL) ----


def _catalog(url: str) -> dict[str, list[tuple[object, ...]]]:
    queries = {
        "contraintes": """
            SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)
            FROM pg_constraint WHERE connamespace = 'public'::regnamespace
              AND conrelid::regclass::text <> 'alembic_version' ORDER BY 1, 2""",
        "index": """
            SELECT tablename, indexname, indexdef FROM pg_indexes
            WHERE schemaname = 'public' AND tablename <> 'alembic_version' ORDER BY 1, 2""",
        "colonnes": """
            SELECT table_name, column_name, data_type, is_nullable, column_default,
                   is_identity, identity_generation
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name <> 'alembic_version' ORDER BY 1, 2""",
    }
    with connect(url) as conn:
        return {name: [tuple(r) for r in conn.execute(sa.text(q))] for name, q in queries.items()}


def test_constraints_indexes_and_columns_match_tables_py_as_rendered_by_postgresql(
    migrated: str, new_database: Callable[[], str]
) -> None:
    built = new_database()
    engine = sa.create_engine(built, poolclass=sa.pool.NullPool)
    try:
        t.metadata.create_all(engine)
    finally:
        engine.dispose()
    from_migrations, from_metadata = _catalog(migrated), _catalog(built)
    for kind in from_migrations:
        assert from_migrations[kind] == from_metadata[kind], kind
    assert len(from_migrations["contraintes"]) > 50  # la comparaison n'est pas vide


# --- Idempotence : portée par projet ----------------------------------------------------------


def seed_step(conn: sa.Connection, execution_id: UUID, project_id: UUID, seq: int = 1) -> UUID:
    return conn.execute(
        sa.insert(t.execution_steps)
        .values(
            execution_id=execution_id,
            project_id=project_id,
            seq=seq,
            tool="x",
            params={},
            idempotency_key=f"k{seq}",
        )
        .returning(t.execution_steps.c.id)
    ).scalar_one()


def seed_run(conn: sa.Connection) -> tuple[UUID, UUID, UUID, UUID]:
    """(projet, plan, exécution, étape) cohérents."""
    project = seed_project(conn)
    plan = seed_plan(conn, project)
    execution = seed_execution(conn, plan, project, "running")
    return project, plan, execution, seed_step(conn, execution, project)


def test_the_same_key_is_accepted_in_two_projects_and_rejected_twice_in_one(
    migrated: str,
) -> None:
    with connect(migrated) as conn:
        a, _, _, step_a = seed_run(conn)
        b, _, _, step_b = seed_run(conn)
        for project, step in ((a, step_a), (b, step_b)):
            conn.execute(
                sa.insert(t.step_idempotency).values(project_id=project, key="same", step_id=step)
            )
    with (
        pytest.raises(IntegrityError, match="step_idempotency_pkey"),
        connect(migrated) as conn,
    ):
        conn.execute(sa.insert(t.step_idempotency).values(project_id=a, key="same", step_id=step_a))


def test_a_done_reservation_must_carry_a_result(migrated: str) -> None:
    with connect(migrated) as conn:
        project, _, _, step = seed_run(conn)
    with (
        pytest.raises(IntegrityError, match="step_idempotency_result"),
        connect(migrated) as conn,
    ):
        conn.execute(
            sa.insert(t.step_idempotency).values(
                project_id=project, key="k", step_id=step, status="done"
            )
        )


# --- États et bornes --------------------------------------------------------------------------


def test_production_never_runs_at_autonomy_level_4_but_staging_may(migrated: str) -> None:
    with connect(migrated) as conn:
        project = seed_project(conn)
        plans = [seed_plan(conn, project, v, f"sha256:{v:064d}") for v in (1, 2, 3)]
    values = {"project_id": project, "state": "succeeded"}
    with connect(migrated) as conn:  # staging niveau 4 et production niveau 3 : permis
        conn.execute(
            sa.insert(t.executions).values(
                plan_id=plans[0], environment="staging", autonomy_level=4, **values
            )
        )
        conn.execute(
            sa.insert(t.executions).values(
                plan_id=plans[1], environment="production", autonomy_level=3, **values
            )
        )
    with (
        pytest.raises(IntegrityError, match="executions_production_autonomy"),
        connect(migrated) as conn,
    ):
        conn.execute(
            sa.insert(t.executions).values(
                plan_id=plans[2], environment="production", autonomy_level=4, **values
            )
        )


def test_awaiting_approval_is_not_an_execution_state(migrated: str) -> None:
    with connect(migrated) as conn:
        project = seed_project(conn)
        plan = seed_plan(conn, project)
    with pytest.raises(IntegrityError, match="executions_state"), connect(migrated) as conn:
        seed_execution(conn, plan, project, "awaiting_approval")


@pytest.mark.parametrize("active_state", ["running", "awaiting_permission", "awaiting_remediation"])
def test_each_active_state_blocks_a_second_active_execution(
    migrated: str, active_state: str
) -> None:
    with connect(migrated) as conn:
        project = seed_project(conn)
        first, second = seed_plan(conn, project, 1), seed_plan(conn, project, 2)
        seed_execution(conn, first, project, active_state)
    with (
        pytest.raises(IntegrityError, match="uq_executions_one_active_per_project"),
        connect(migrated) as conn,
    ):
        seed_execution(conn, second, project, "running")


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        ("UPDATE executions SET lease_epoch = -1", "executions_lease_epoch"),
        ("UPDATE projects SET status = 'bogus'", "projects_status"),
    ],
)
def test_bounded_columns(migrated: str, statement: str, constraint: str) -> None:
    with connect(migrated) as conn:
        seed_run(conn)
    with pytest.raises(IntegrityError, match=constraint), connect(migrated) as conn:
        conn.execute(sa.text(statement))


def test_a_plan_version_starts_at_one(migrated: str) -> None:
    with connect(migrated) as conn:
        project = seed_project(conn)
    with pytest.raises(IntegrityError, match="plans_version"), connect(migrated) as conn:
        seed_plan(conn, project, version_=0)


# --- Isolation entre projets en aval des exécutions -------------------------------------------


def test_a_step_cannot_be_attached_to_the_execution_of_another_project(migrated: str) -> None:
    with connect(migrated) as conn:
        _, _, execution_of_a, _ = seed_run(conn)
        project_b = seed_project(conn)
    with (
        pytest.raises(IntegrityError, match="execution_steps_execution_id_project_id_fkey"),
        connect(migrated) as conn,
    ):
        seed_step(conn, execution_of_a, project_b, seq=2)


def test_a_reservation_cannot_point_to_a_step_of_another_project(migrated: str) -> None:
    with connect(migrated) as conn:
        _, _, _, step_of_a = seed_run(conn)
        project_b = seed_project(conn)
    with (
        pytest.raises(IntegrityError, match="step_idempotency_step_id_project_id_fkey"),
        connect(migrated) as conn,
    ):
        conn.execute(
            sa.insert(t.step_idempotency).values(project_id=project_b, key="k", step_id=step_of_a)
        )


def test_a_resource_cannot_cite_the_execution_or_step_of_another_project(migrated: str) -> None:
    with connect(migrated) as conn:
        _, _, execution_of_a, step_of_a = seed_run(conn)
        project_b = seed_project(conn)
        free = {"project_id": project_b, "provider": "gitlab", "resource_type": "group"}
        # NULL permis : une ressource sans exécution ni étape (adoption) reste valide.
        conn.execute(sa.insert(t.managed_resources).values(external_id="adopted", **free))
    with (
        pytest.raises(IntegrityError, match="managed_resources_execution_id_project_id_fkey"),
        connect(migrated) as conn,
    ):
        conn.execute(
            sa.insert(t.managed_resources).values(
                external_id="e", execution_id=execution_of_a, **free
            )
        )
    with (
        pytest.raises(IntegrityError, match="managed_resources_step_id_project_id_fkey"),
        connect(migrated) as conn,
    ):
        conn.execute(
            sa.insert(t.managed_resources).values(external_id="s", step_id=step_of_a, **free)
        )


def test_an_observation_cannot_cite_a_resource_of_another_project(migrated: str) -> None:
    with connect(migrated) as conn:
        project_a = seed_project(conn)
        resource = conn.execute(
            sa.insert(t.managed_resources)
            .values(project_id=project_a, provider="g", resource_type="r", external_id="x")
            .returning(t.managed_resources.c.id)
        ).scalar_one()
        project_b = seed_project(conn)
    with (
        pytest.raises(IntegrityError, match="observed_state_resource_id_project_id_fkey"),
        connect(migrated) as conn,
    ):
        conn.execute(
            sa.insert(t.observed_state).values(
                resource_id=resource, project_id=project_b, observed={}
            )
        )


# --- Un plan approuvé ne change plus de contenu -----------------------------------------------


@pytest.mark.parametrize(
    "assignment",
    [
        "content = '{\"steps\": []}'::jsonb",
        "content_hash = 'sha256:other'",
        "version = 2",
        "project_id = (SELECT id FROM projects WHERE id <> plans.project_id)",
        "skills_used = '[1]'::jsonb",
    ],
)
def test_the_content_of_a_plan_is_immutable(migrated: str, assignment: str) -> None:
    with connect(migrated) as conn:
        seed_run(conn)
        seed_project(conn)  # un second projet, cible du déplacement
    with pytest.raises(DBAPIError, match="immutable"), connect(migrated) as conn:
        conn.execute(sa.text(f"UPDATE plans SET {assignment}"))  # noqa: S608 - constantes du test


def test_status_and_expiry_of_a_plan_remain_editable(migrated: str) -> None:
    with connect(migrated) as conn:
        seed_run(conn)
        conn.execute(
            sa.text(
                "UPDATE plans SET status = 'dev_approved', expires_at = now() + interval '2 days'"
            )
        )
        status = conn.execute(sa.select(t.plans.c.status)).scalar_one()
    assert status == "dev_approved"


# --- Retour arrière et verrou -----------------------------------------------------------------


def test_downgrade_refuses_to_drop_a_non_empty_audit_log_unless_forced(
    migrated: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connect(migrated) as conn:
        conn.execute(sa.insert(t.audit_events).values(actor_kind="system"))
    monkeypatch.delenv(ENV_ALLOW_DESTRUCTIVE_DOWNGRADE)
    with pytest.raises(RuntimeError, match="retour arrière refusé"):
        downgrade(migrated, "base")
    assert "audit_events" in table_names(migrated)  # rien n'a été supprimé
    monkeypatch.setenv(ENV_ALLOW_DESTRUCTIVE_DOWNGRADE, "1")
    downgrade(migrated, "base")
    assert table_names(migrated) == set()


def test_a_held_migration_lock_gives_a_clear_error_after_the_deadline(
    blank_database_url: str,
) -> None:
    holder_ready, release = threading.Event(), threading.Event()

    def hold() -> None:
        with connect(blank_database_url) as conn:
            conn.execute(sa.text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
            holder_ready.set()
            release.wait(timeout=30)

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert holder_ready.wait(timeout=10)
    try:
        with pytest.raises(RuntimeError, match="verrou de migration non obtenu"):
            upgrade_head(blank_database_url, lock_timeout_s=0.5)
    finally:
        release.set()
        thread.join(timeout=10)
    assert table_names(blank_database_url) == set()  # rien n'a été migré sans le verrou
    upgrade_head(blank_database_url)  # le verrou libéré, la migration passe
