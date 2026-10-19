"""Migrations sur un vrai PostgreSQL : base neuve par test (voir tests/conftest.py)."""

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import DBAPIError, IntegrityError

from foreman.infra.db import tables as t
from foreman.infra.db.migrate import downgrade, upgrade_head

EXPECTED_TABLES = {
    "users",
    "teams",
    "projects",
    "plans",
    "approvals",
    "executions",
    "execution_steps",
    "step_idempotency",
    "managed_resources",
    "observed_state",
    "audit_events",
    "project_events",
    "memberships",
}
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


@contextmanager
def connect(url: str) -> Iterator[sa.Connection]:
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.begin() as conn:
            yield conn
    finally:
        engine.dispose()


def table_names(url: str) -> set[str]:
    with connect(url) as conn:
        return set(sa.inspect(conn).get_table_names()) - {"alembic_version"}


def version(url: str) -> str | None:
    with connect(url) as conn:
        return conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()


def seed_project(conn: sa.Connection) -> UUID:
    team = conn.execute(
        sa.insert(t.teams).values(name=f"team-{uuid4().hex}").returning(t.teams.c.id)
    ).scalar_one()
    return conn.execute(
        sa.insert(t.projects).values(team_id=team, name="p").returning(t.projects.c.id)
    ).scalar_one()


def seed_plan(
    conn: sa.Connection, project_id: UUID, version_: int = 1, hash_: str = HASH_A
) -> UUID:
    return conn.execute(
        sa.insert(t.plans)
        .values(
            project_id=project_id,
            version=version_,
            content={},
            content_hash=hash_,
            skills_used=[],
            expires_at=sa.func.now() + sa.text("interval '1 day'"),
        )
        .returning(t.plans.c.id)
    ).scalar_one()


def seed_execution(conn: sa.Connection, plan_id: UUID, project_id: UUID, state: str) -> UUID:
    return conn.execute(
        sa.insert(t.executions)
        .values(
            plan_id=plan_id,
            project_id=project_id,
            state=state,
            autonomy_level=2,
            environment="staging",
        )
        .returning(t.executions.c.id)
    ).scalar_one()


def test_empty_database_gets_the_full_schema(blank_database_url: str) -> None:
    upgrade_head(blank_database_url)
    assert table_names(blank_database_url) == EXPECTED_TABLES
    assert version(blank_database_url) == "0005"


def test_running_twice_changes_nothing(blank_database_url: str) -> None:
    upgrade_head(blank_database_url)
    with connect(blank_database_url) as conn:
        conn.execute(sa.insert(t.teams).values(name="dev"))
    upgrade_head(blank_database_url)
    assert version(blank_database_url) == "0005"
    with connect(blank_database_url) as conn:
        assert conn.execute(sa.select(sa.func.count()).select_from(t.teams)).scalar() == 1


def test_two_concurrent_upgrades_both_succeed(blank_database_url: str) -> None:
    barrier = threading.Barrier(2)

    def run() -> None:
        barrier.wait(timeout=10)
        upgrade_head(blank_database_url)

    pool = ThreadPoolExecutor(max_workers=2)
    try:
        futures = [pool.submit(run) for _ in range(2)]
        for future in futures:
            future.result(timeout=30)  # propage l'exception d'un des deux si elle a échoué
    finally:
        # Sans attendre : une migration bloquée est libérée par la suppression de la base.
        pool.shutdown(wait=False, cancel_futures=True)
    assert table_names(blank_database_url) == EXPECTED_TABLES
    assert version(blank_database_url) == "0005"


def test_downgrade_to_base_removes_everything_then_upgrade_works_again(
    blank_database_url: str,
) -> None:
    upgrade_head(blank_database_url)
    downgrade(blank_database_url, "base")
    assert table_names(blank_database_url) == set()
    with connect(blank_database_url) as conn:
        functions = conn.execute(
            sa.text("SELECT proname FROM pg_proc WHERE proname = 'forbid_mutation'")
        ).all()
    assert functions == []
    upgrade_head(blank_database_url)
    assert table_names(blank_database_url) == EXPECTED_TABLES


def test_the_metadata_matches_the_migrated_database(blank_database_url: str) -> None:
    upgrade_head(blank_database_url)
    with connect(blank_database_url) as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(context, t.metadata)
    assert diff == []


@pytest.fixture
def audited_database(blank_database_url: str) -> str:
    upgrade_head(blank_database_url)
    with connect(blank_database_url) as conn:
        conn.execute(sa.insert(t.audit_events).values(actor_kind="system", decision="allow"))
    return blank_database_url


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET decision = 'deny'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
        "TRUNCATE audit_events, observed_state",
    ],
)
def test_audit_events_is_append_only(audited_database: str, statement: str) -> None:
    with pytest.raises(DBAPIError, match="append-only"), connect(audited_database) as conn:
        conn.execute(sa.text(statement))
    with connect(audited_database) as conn:
        rows = conn.execute(sa.select(t.audit_events.c.decision)).scalars().all()
    assert rows == ["allow"]


def test_a_resource_cannot_be_registered_twice(blank_database_url: str) -> None:
    upgrade_head(blank_database_url)
    values = {"provider": "gitlab", "resource_type": "group", "external_id": "42"}
    with connect(blank_database_url) as conn:
        project = seed_project(conn)
        conn.execute(sa.insert(t.managed_resources).values(project_id=project, **values))
    with (
        pytest.raises(IntegrityError, match="managed_resources_provider"),
        connect(blank_database_url) as conn,
    ):
        other = seed_project(conn)
        conn.execute(sa.insert(t.managed_resources).values(project_id=other, **values))


def test_a_plan_runs_at_most_once(blank_database_url: str) -> None:
    upgrade_head(blank_database_url)
    with connect(blank_database_url) as conn:
        project = seed_project(conn)
        plan = seed_plan(conn, project)
        seed_execution(conn, plan, project, "succeeded")
    with (
        pytest.raises(IntegrityError, match="executions_plan_id_key"),
        connect(blank_database_url) as conn,
    ):
        seed_execution(conn, plan, project, "blocked")


def test_a_project_has_one_active_execution_but_many_finished(blank_database_url: str) -> None:
    upgrade_head(blank_database_url)
    with connect(blank_database_url) as conn:
        project = seed_project(conn)
        plans = [seed_plan(conn, project, v) for v in (1, 2, 3, 4)]
        seed_execution(conn, plans[0], project, "succeeded")
        seed_execution(conn, plans[1], project, "blocked")
        seed_execution(conn, plans[2], project, "running")
    with (
        pytest.raises(IntegrityError, match="uq_executions_one_active_per_project"),
        connect(blank_database_url) as conn,
    ):
        seed_execution(conn, plans[3], project, "awaiting_permission")


def test_an_execution_cannot_point_to_the_plan_of_another_project(blank_database_url: str) -> None:
    upgrade_head(blank_database_url)
    with connect(blank_database_url) as conn:
        project_a = seed_project(conn)
        team = conn.execute(sa.select(t.teams.c.id)).scalar_one()
        project_b = conn.execute(
            sa.insert(t.projects).values(team_id=team, name="b").returning(t.projects.c.id)
        ).scalar_one()
        plan_of_a = seed_plan(conn, project_a)
    with (
        pytest.raises(IntegrityError, match="executions_plan_id_project_id_fkey"),
        connect(blank_database_url) as conn,
    ):
        seed_execution(conn, plan_of_a, project_b, "running")


def test_an_approval_must_carry_the_hash_of_its_plan(blank_database_url: str) -> None:
    upgrade_head(blank_database_url)
    with connect(blank_database_url) as conn:
        project = seed_project(conn)
        plan = seed_plan(conn, project, hash_=HASH_A)
        user = conn.execute(
            sa.insert(t.users).values(email="a@b.c", name="a").returning(t.users.c.id)
        ).scalar_one()
        approval = {
            "plan_id": plan,
            "kind": "developer",
            "approver_id": user,
            "decision": "approved",
        }
        conn.execute(sa.insert(t.approvals).values(plan_hash=HASH_A, **approval))
    with (
        pytest.raises(IntegrityError, match="approvals_plan_id_plan_hash_fkey"),
        connect(blank_database_url) as conn,
    ):
        conn.execute(
            sa.insert(t.approvals).values(plan_hash=HASH_B, **approval | {"kind": "admin"})
        )
    with (
        pytest.raises(IntegrityError, match="uq_approvals_plan_kind_approved"),
        connect(blank_database_url) as conn,
    ):
        conn.execute(sa.insert(t.approvals).values(plan_hash=HASH_A, **approval))  # double


def test_0003_fills_environment_from_the_plan_and_downgrades_without_losing_executions(
    blank_database_url: str,
) -> None:
    upgrade_head(blank_database_url)
    downgrade(blank_database_url, "0002")  # schéma d'avant : exécutions sans `environment`
    with connect(blank_database_url) as conn:
        team = conn.execute(sa.text("INSERT INTO teams (name) VALUES ('t') RETURNING id")).scalar()
        project = conn.execute(
            sa.text("INSERT INTO projects (team_id) VALUES (:t) RETURNING id"), {"t": team}
        ).scalar()
        for number, content in enumerate(('{"environment": "production"}', "{}"), start=1):
            conn.execute(
                sa.text(
                    "INSERT INTO plans (project_id, version, content, content_hash, skills_used,"
                    " expires_at) VALUES (:p, :v, CAST(:c AS jsonb), :h, '[]', now())"
                ),
                {"p": project, "v": number, "c": content, "h": f"sha256:{number:064d}"},
            )
        conn.execute(
            sa.text(
                "INSERT INTO executions (plan_id, project_id, state, autonomy_level)"
                " SELECT id, project_id, 'succeeded', 3 FROM plans"
            )
        )
    upgrade_head(blank_database_url)
    with connect(blank_database_url) as conn:
        rows = conn.execute(sa.text("SELECT environment FROM executions ORDER BY 1")).scalars()
        assert list(rows) == ["production", "staging"]  # plan sans environnement : staging
    downgrade(blank_database_url, "0002")
    with connect(blank_database_url) as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM executions")).scalar() == 2


def test_0004_prefixes_server_projects_with_their_environment_and_downgrades(
    blank_database_url: str,
) -> None:
    upgrade_head(blank_database_url)
    downgrade(blank_database_url, "0003")
    with connect(blank_database_url) as conn:
        project = seed_project(conn)
        execution = seed_execution(conn, seed_plan(conn, project), project, "succeeded")
        conn.execute(
            sa.insert(t.managed_resources).values(
                project_id=project,
                execution_id=execution,
                provider="server",
                resource_type="server_project",
                external_id="safe-eat",
            )
        )
    upgrade_head(blank_database_url)
    with connect(blank_database_url) as conn:
        assert conn.execute(sa.select(t.managed_resources.c.external_id)).scalar() == (
            "staging/safe-eat"
        )
    downgrade(blank_database_url, "0003")
    with connect(blank_database_url) as conn:
        assert conn.execute(sa.select(t.managed_resources.c.external_id)).scalar() == "safe-eat"


def test_0005_fills_existing_refusals_and_the_check_ties_invalidation_to_the_status(
    blank_database_url: str,
) -> None:
    upgrade_head(blank_database_url)
    downgrade(blank_database_url, "0004")
    with connect(blank_database_url) as conn:
        project = seed_project(conn)
        rejected = seed_plan(conn, project, 1, HASH_A)
        seed_plan(conn, project, 2, HASH_B)  # `proposed` : reste sans raison
        conn.execute(
            sa.text("UPDATE plans SET status = 'invalidated' WHERE id = :i"), {"i": rejected}
        )
    upgrade_head(blank_database_url)
    with connect(blank_database_url) as conn:
        rows = dict(conn.execute(sa.select(t.plans.c.version, t.plans.c.invalidation)).all())
        assert rows == {1: {"reason": "admin_rejected", "changes": []}, 2: None}
    for values in ({"status": "invalidated"}, {"invalidation": {"reason": "x", "changes": []}}):
        with pytest.raises(IntegrityError), connect(blank_database_url) as conn:
            conn.execute(sa.update(t.plans).where(t.plans.c.version == 2).values(**values))
    with connect(blank_database_url) as conn:  # `expired` n'a pas de raison en colonne
        conn.execute(sa.update(t.plans).where(t.plans.c.version == 2).values(status="expired"))
    downgrade(blank_database_url, "0004")
    with connect(blank_database_url) as conn:
        columns = {c["name"] for c in sa.inspect(conn).get_columns("plans")}
        assert "invalidation" not in columns
        assert conn.execute(
            sa.text("SELECT status FROM plans ORDER BY version")
        ).scalars().all() == [
            "invalidated",
            "expired",
        ]
