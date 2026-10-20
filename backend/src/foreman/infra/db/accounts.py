"""Comptes, équipes, appartenances et invitations en PostgreSQL.

Invariants (au moins un org_admin actif ; au moins un admin actif par équipe non personnelle) :
chaque mutation qui peut les entamer verrouille d'abord, dans un ordre fixe `(team_id, user_id)`,
les lignes `memberships` des org_admin et de l'équipe visée (`SELECT ... FOR UPDATE`), puis relit
l'état avec une requête neuve. Deux opérations concurrentes se sérialisent donc, sans interblocage.
"""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from foreman.core.accounts import (
    ADMIN_ROLES,
    Account,
    AdminScope,
    AdminUser,
    Conflict,
    ElevationDenied,
    InvalidInvitation,
    Invitation,
    LastAdmin,
    LastTeamAdmin,
    Membership,
    NotFound,
    PersonalTeam,
    Team,
    rank,
    require_grant,
    validate_inviter_chain,
)
from foreman.core.identity import Role
from foreman.core.ports import CapacityExceeded
from foreman.core.store import StoreError
from foreman.infra.db import tables as t
from foreman.infra.db.engine import log_failure

MAX_ACCOUNTS = 1_000
MAX_TEAMS = 500
MAX_PENDING_INVITATIONS = 1_000
# Verrou transactionnel qui sérialise les créations (plafonds atomiques).
ACCOUNT_CREATE_LOCK_KEY = 7_361_530_003

_M = t.memberships
_U = t.users


class PostgresAccountStore:
    def __init__(
        self,
        engine: AsyncEngine,
        max_accounts: int = MAX_ACCOUNTS,
        max_teams: int = MAX_TEAMS,
        max_pending_invitations: int = MAX_PENDING_INVITATIONS,
    ) -> None:
        self._engine = engine
        self._max_accounts = max_accounts
        self._max_teams = max_teams
        self._max_invitations = max_pending_invitations

    async def create_account(
        self,
        email: str,
        name: str,
        password_hash: str | None,
        *,
        invited_by: UUID | None = None,
        role: Role = "team_admin",
    ) -> Account:
        async with self._tx("account.create") as conn:
            return await self._insert_account(conn, email, name, password_hash, invited_by, role)

    async def create_team(self, name: str, first_admin: UUID, actor: UUID | None = None) -> Team:
        async with self._tx("team.create") as conn:
            if actor is not None and await self._actor_role(conn, actor, None) != "org_admin":
                raise ElevationDenied("droits insuffisants")
            await self._cap(conn, t.teams, self._max_teams)
            await self._require_active(conn, first_admin)
            team = await self._insert_team(conn, name, personal=False)
            await conn.execute(
                sa.insert(_M).values(user_id=first_admin, team_id=team.id, role="team_admin")
            )
            await self._audit(conn, actor, "team.create", team.id, None, str(first_admin))
            return team

    async def add_member(self, team_id: UUID, user_id: UUID, role: Role, actor: UUID) -> None:
        async with self._tx("member.add") as conn:
            require_grant(await self._actor_role(conn, actor, team_id), role)
            await self._require_active(conn, user_id)
            await self._require_shared_team(conn, team_id)
            await conn.execute(sa.insert(_M).values(user_id=user_id, team_id=team_id, role=role))
            await self._audit(conn, actor, "member.add", f"{team_id}/{user_id}", None, role)

    async def change_role(self, team_id: UUID, user_id: UUID, role: Role, actor: UUID) -> None:
        async with self._tx("member.change_role") as conn:
            await self._lock(conn, [team_id])
            old = await self._role_in(conn, team_id, user_id)
            if old is None:
                raise NotFound("membre introuvable")
            actor_role = await self._actor_role(conn, actor, team_id)
            require_grant(actor_role, role)
            require_grant(actor_role, old)  # on ne rétrograde pas plus haut que soi
            await self._guard(conn, user_id, team_id, old, role)
            await conn.execute(
                sa.update(_M)
                .where(_M.c.team_id == team_id, _M.c.user_id == user_id)
                .values(role=role)
            )
            await self._audit(conn, actor, "member.change_role", f"{team_id}/{user_id}", old, role)

    async def remove_member(self, team_id: UUID, user_id: UUID, actor: UUID) -> None:
        async with self._tx("member.remove") as conn:
            await self._lock(conn, [team_id])
            old = await self._role_in(conn, team_id, user_id)
            if old is None:
                raise NotFound("membre introuvable")
            require_grant(await self._actor_role(conn, actor, team_id), old)
            await self._guard(conn, user_id, team_id, old, None)
            await conn.execute(
                sa.delete(_M).where(_M.c.team_id == team_id, _M.c.user_id == user_id)
            )
            await self._audit(conn, actor, "member.remove", f"{team_id}/{user_id}", old, None)

    async def disable_account(self, user_id: UUID, actor: UUID) -> None:
        async with self._tx("account.disable") as conn:
            teams = await self._teams_of(conn, user_id)
            await self._lock(conn, teams)
            memberships = (
                await conn.execute(
                    sa.select(_M.c.team_id, _M.c.role).where(_M.c.user_id == user_id)
                )
            ).all()
            if not memberships and not await self._exists(conn, user_id):
                raise NotFound("compte introuvable")
            for team_id, role in memberships:
                require_grant(await self._actor_role(conn, actor, team_id), role)
            if any(role == "org_admin" for _, role in memberships):
                await self._guard(conn, user_id, None, "org_admin", None)
            for team_id, role in memberships:
                if role in ADMIN_ROLES:
                    await self._guard(conn, user_id, None, role, None, only_team=team_id)
            await conn.execute(
                sa.update(_U).where(_U.c.id == user_id).values(disabled_at=sa.func.now())
            )
            await conn.execute(sa.delete(t.sessions).where(t.sessions.c.user_id == user_id))
            await self._audit(conn, actor, "account.disable", user_id, "active", "disabled")

    async def create_invitation(
        self,
        token_hash: str,
        email: str,
        team_id: UUID | None,
        role: Role,
        invited_by: UUID,
        expires_at: datetime,
    ) -> Invitation:
        async with self._tx("invitation.create") as conn:
            require_grant(await self._actor_role(conn, invited_by, team_id), role)
            if team_id is not None:
                await self._require_shared_team(conn, team_id)
            await self._cap(
                conn, t.invitations, self._max_invitations, t.invitations.c.used_at.is_(None)
            )
            row = (
                await conn.execute(
                    sa.insert(t.invitations)
                    .values(
                        token_hash=token_hash,
                        email=email.lower(),
                        team_id=team_id,
                        role=role,
                        invited_by=invited_by,
                        expires_at=expires_at,
                    )
                    .returning(t.invitations.c.id)
                )
            ).scalar_one()
            await self._audit(conn, invited_by, "invitation.create", row, None, role)
            return Invitation(row, email.lower(), team_id, role, invited_by, expires_at)

    async def accept_invitation(
        self, token_hash: str, email: str, name: str, password_hash: str, now: datetime
    ) -> Account:
        async with self._tx("invitation.accept") as conn:
            # Consommation atomique : une seule transaction obtient la ligne (used_at IS NULL).
            inv = (
                await conn.execute(
                    sa.update(t.invitations)
                    .where(
                        t.invitations.c.token_hash == token_hash,
                        t.invitations.c.used_at.is_(None),
                        t.invitations.c.expires_at > now,
                    )
                    .values(used_at=now)
                    .returning(
                        t.invitations.c.team_id,
                        t.invitations.c.role,
                        t.invitations.c.invited_by,
                        t.invitations.c.email,
                    )
                )
            ).one_or_none()
            if inv is None or inv.email != email.lower():
                raise InvalidInvitation("invitation invalide")  # annule aussi la consommation
            # L'auteur doit toujours avoir le droit d'accorder ce rôle (il a pu être rétrogradé).
            require_grant(await self._actor_role(conn, inv.invited_by, inv.team_id), inv.role)
            # Premier mot de passe d'un compte créé sans (CLI `admin create`) : pas de doublon.
            existing = (
                await conn.execute(
                    sa.select(_U.c.id, _U.c.name, _U.c.password_hash, _U.c.disabled_at)
                    .where(sa.func.lower(_U.c.email) == email.lower())
                    .with_for_update()
                )
            ).one_or_none()
            if existing is not None:
                if existing.password_hash is not None or existing.disabled_at is not None:
                    raise InvalidInvitation("invitation invalide")
                await conn.execute(
                    sa.update(_U).where(_U.c.id == existing.id).values(password_hash=password_hash)
                )
                return Account(existing.id, email.lower(), existing.name, None, inv.invited_by)
            account = await self._insert_account(
                conn,
                email,
                name,
                password_hash,
                inv.invited_by,
                "org_admin" if inv.team_id is None and inv.role == "org_admin" else "team_admin",
            )
            if inv.team_id is not None:
                await conn.execute(
                    sa.insert(_M).values(user_id=account.id, team_id=inv.team_id, role=inv.role)
                )
            return account

    async def admin_scope(self, user_id: UUID) -> AdminScope:
        async with self._tx("account.admin_scope") as conn:
            rows = (
                await conn.execute(
                    sa.select(_M.c.team_id, _M.c.role, t.teams.c.personal)
                    .select_from(
                        _M.join(_U, _U.c.id == _M.c.user_id).join(
                            t.teams, t.teams.c.id == _M.c.team_id
                        )
                    )
                    .where(_M.c.user_id == user_id, _U.c.disabled_at.is_(None))
                )
            ).all()
        return AdminScope(
            org=any(r.role == "org_admin" for r in rows),
            teams=frozenset(r.team_id for r in rows if r.role == "team_admin" and not r.personal),
        )

    async def memberships(
        self, user_ids: Sequence[UUID], team_ids: Collection[UUID] | None = None
    ) -> dict[UUID, list[Membership]]:
        query = (
            sa.select(_M.c.user_id, _M.c.team_id, t.teams.c.name, _M.c.role)
            .select_from(_M.join(t.teams, t.teams.c.id == _M.c.team_id))
            .where(_M.c.user_id.in_(list(user_ids)), t.teams.c.personal.is_(False))
            .order_by(t.teams.c.name)
        )
        if team_ids is not None:
            query = query.where(_M.c.team_id.in_(list(team_ids)))
        async with self._tx("account.memberships") as conn:
            rows = (await conn.execute(query)).all()
        found: dict[UUID, list[Membership]] = {}
        for r in rows:
            found.setdefault(r.user_id, []).append(Membership(r.team_id, r.name, r.role))
        return found

    async def list_teams(self, team_ids: Collection[UUID] | None, limit: int) -> list[Team]:
        query = (
            sa.select(t.teams.c.id, t.teams.c.name)
            .where(t.teams.c.personal.is_(False))
            .order_by(t.teams.c.name)
            .limit(limit)
        )
        if team_ids is not None:
            query = query.where(t.teams.c.id.in_(list(team_ids)))
        async with self._tx("team.list") as conn:
            return [Team(r.id, r.name) for r in (await conn.execute(query)).all()]

    async def list_users(self, team_ids: Collection[UUID] | None, limit: int) -> list[AdminUser]:
        query = sa.select(_U.c.id, _U.c.email, _U.c.name, _U.c.disabled_at).order_by(_U.c.email)
        if team_ids is not None:
            members = sa.select(_M.c.user_id).where(_M.c.team_id.in_(list(team_ids)))
            query = query.where(_U.c.id.in_(members))
        async with self._tx("account.list") as conn:
            rows = (await conn.execute(query.limit(limit))).all()
        found = await self.memberships([r.id for r in rows], team_ids)
        return [
            AdminUser(r.id, r.email, r.name, r.disabled_at is not None, tuple(found.get(r.id, ())))
            for r in rows
        ]

    async def list_invitations(
        self, team_ids: Collection[UUID] | None, limit: int
    ) -> list[Invitation]:
        i = t.invitations
        query = sa.select(*i.c).where(i.c.used_at.is_(None)).order_by(i.c.expires_at.desc())
        if team_ids is not None:
            query = query.where(i.c.team_id.in_(list(team_ids)))
        async with self._tx("invitation.list") as conn:
            rows = (await conn.execute(query.limit(limit))).all()
        return [
            Invitation(r.id, r.email, r.team_id, r.role, r.invited_by, r.expires_at, r.used_at)
            for r in rows
        ]

    async def revoke_invitation(self, invitation_id: UUID, actor: UUID) -> None:
        i = t.invitations
        async with self._tx("invitation.revoke") as conn:
            row = (
                await conn.execute(
                    sa.select(i.c.team_id, i.c.role, i.c.used_at)
                    .where(i.c.id == invitation_id)
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                raise NotFound("invitation introuvable")
            actor_role = await self._actor_role(conn, actor, row.team_id)
            if actor_role not in ADMIN_ROLES:
                raise ElevationDenied("droits insuffisants")
            require_grant(actor_role, row.role)
            if row.used_at is not None:
                raise InvalidInvitation("invitation déjà utilisée")
            await conn.execute(sa.delete(i).where(i.c.id == invitation_id))
            await self._audit(conn, actor, "invitation.revoke", invitation_id, row.role, None)

    async def move_project(self, project_id: UUID, team_id: UUID, actor: UUID) -> None:
        async with self._tx("project.move") as conn:
            if await self._actor_role(conn, actor, None) != "org_admin":
                raise ElevationDenied("droits insuffisants")
            await self._require_shared_team(conn, team_id)
            old = (
                await conn.execute(
                    sa.select(t.projects.c.team_id)
                    .where(t.projects.c.id == project_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if old is None:
                raise NotFound("projet introuvable")
            await conn.execute(
                sa.update(t.projects).where(t.projects.c.id == project_id).values(team_id=team_id)
            )
            await self._audit(conn, actor, "project.move", project_id, str(old), str(team_id))

    # --- internes -------------------------------------------------------------------------

    def _tx(self, operation: str) -> "_Tx":
        return _Tx(self._engine, operation)

    async def _audit(
        self,
        conn: AsyncConnection,
        actor: UUID | None,
        action: str,
        target: object,
        old: str | None,
        new: str | None,
    ) -> None:
        """Dans la transaction de la mutation ; identifiants et rôles, jamais de secret."""
        await conn.execute(
            sa.insert(t.audit_events).values(
                actor_kind="user",
                actor_id=actor,
                tool=f"identity.{action}",
                decision="allow",
                params_redacted={"cible": str(target), "ancien": old, "nouveau": new},
            )
        )

    async def _cap(self, conn: AsyncConnection, table: sa.Table, limit: int, *where: Any) -> None:
        await conn.execute(sa.select(sa.func.pg_advisory_xact_lock(ACCOUNT_CREATE_LOCK_KEY)))
        count = (
            await conn.execute(sa.select(sa.func.count()).select_from(table).where(*where))
        ).scalar_one()
        if count >= limit:
            raise CapacityExceeded

    async def _insert_team(self, conn: AsyncConnection, name: str, *, personal: bool) -> Team:
        row = (
            await conn.execute(
                sa.insert(t.teams).values(name=name, personal=personal).returning(t.teams.c.id)
            )
        ).scalar_one()
        return Team(row, name, personal)

    async def _insert_account(
        self,
        conn: AsyncConnection,
        email: str,
        name: str,
        password_hash: str | None,
        invited_by: UUID | None,
        role: Role,
    ) -> Account:
        await self._cap(conn, _U, self._max_accounts)
        await self._cap(conn, t.teams, self._max_teams)
        if invited_by is not None:
            await self._check_chain(conn, invited_by)
        user_id = (
            await conn.execute(
                sa.insert(_U)
                .values(
                    email=email.lower(),
                    name=name,
                    password_hash=password_hash,
                    invited_by=invited_by,
                )
                .returning(_U.c.id)
            )
        ).scalar_one()
        team = await self._insert_team(conn, f"personal-{user_id}", personal=True)
        await conn.execute(sa.insert(_M).values(user_id=user_id, team_id=team.id, role=role))
        return Account(user_id, email.lower(), name, None, invited_by)

    async def _check_chain(self, conn: AsyncConnection, start: UUID) -> None:
        chain = sa.text(
            """
            WITH RECURSIVE c(id, invited_by, depth) AS (
                SELECT id, invited_by, 1 FROM users WHERE id = :start
              UNION ALL
                SELECT u.id, u.invited_by, c.depth + 1 FROM users u JOIN c ON u.id = c.invited_by
                WHERE c.depth < 11
            ) SELECT id, invited_by FROM c
            """
        )
        rows = (await conn.execute(chain, {"start": start})).all()
        validate_inviter_chain(start, {r.id: r.invited_by for r in rows})

    async def _lock(self, conn: AsyncConnection, team_ids: Sequence[UUID]) -> None:
        """Verrouille, dans l'ordre (team_id, user_id), les org_admin et les membres des équipes."""
        await conn.execute(
            sa.select(_M.c.user_id)
            .where(sa.or_(_M.c.role == "org_admin", _M.c.team_id.in_(list(team_ids))))
            .order_by(_M.c.team_id, _M.c.user_id)
            .with_for_update()
        )

    async def _guard(
        self,
        conn: AsyncConnection,
        user_id: UUID,
        team_id: UUID | None,
        old: Role,
        new: Role | None,
        *,
        only_team: UUID | None = None,
    ) -> None:
        """Lève si perdre `old` (remplacé par `new`) laisse l'organisation ou l'équipe sans admin.

        `team_id` None = perte de toutes les appartenances de l'utilisateur (désactivation).
        """

        def others(role_filter: Any, scope: UUID | None) -> sa.Select[Any]:
            query = (
                sa.select(sa.func.count(sa.distinct(_M.c.user_id)))
                .select_from(_M.join(_U, _U.c.id == _M.c.user_id))
                .where(_U.c.disabled_at.is_(None), role_filter)
            )
            if scope is not None:
                query = query.where(_M.c.team_id == scope)
            if team_id is None:
                return query.where(_M.c.user_id != user_id)
            return query.where(sa.not_(sa.and_(_M.c.team_id == team_id, _M.c.user_id == user_id)))

        losing_org = only_team is None and old == "org_admin" and new != "org_admin"
        if (
            losing_org
            and (await conn.execute(others(_M.c.role == "org_admin", None))).scalar_one() == 0
        ):
            raise LastAdmin("dernier org_admin")
        scope = only_team or team_id
        if scope is not None and old in ADMIN_ROLES and new not in ADMIN_ROLES:
            personal = (
                await conn.execute(sa.select(t.teams.c.personal).where(t.teams.c.id == scope))
            ).scalar_one()
            admins = others(_M.c.role.in_(sorted(ADMIN_ROLES)), scope)
            if not personal and (await conn.execute(admins)).scalar_one() == 0:
                raise LastTeamAdmin("dernier admin de l'équipe")

    async def _actor_role(
        self, conn: AsyncConnection, actor: UUID, team_id: UUID | None
    ) -> Role | None:
        """Meilleur rôle actif de l'auteur : org_admin partout, sinon son rôle dans l'équipe."""
        scope = _M.c.role == "org_admin"
        if team_id is not None:
            scope = sa.or_(scope, _M.c.team_id == team_id)
        roles = (
            (
                await conn.execute(
                    sa.select(_M.c.role)
                    .select_from(_M.join(_U, _U.c.id == _M.c.user_id))
                    .where(_M.c.user_id == actor, _U.c.disabled_at.is_(None), scope)
                )
            )
            .scalars()
            .all()
        )
        return max(roles, key=rank, default=None)

    async def _role_in(self, conn: AsyncConnection, team_id: UUID, user_id: UUID) -> Role | None:
        return (
            await conn.execute(
                sa.select(_M.c.role).where(_M.c.team_id == team_id, _M.c.user_id == user_id)
            )
        ).scalar_one_or_none()

    async def _teams_of(self, conn: AsyncConnection, user_id: UUID) -> list[UUID]:
        return list(
            (await conn.execute(sa.select(_M.c.team_id).where(_M.c.user_id == user_id))).scalars()
        )

    async def _exists(self, conn: AsyncConnection, user_id: UUID) -> bool:
        return (
            await conn.execute(sa.select(_U.c.id).where(_U.c.id == user_id))
        ).first() is not None

    async def _require_active(self, conn: AsyncConnection, user_id: UUID) -> None:
        found = await conn.execute(
            sa.select(_U.c.id).where(_U.c.id == user_id, _U.c.disabled_at.is_(None))
        )
        if found.first() is None:
            raise NotFound("compte introuvable")

    async def _require_shared_team(self, conn: AsyncConnection, team_id: UUID) -> None:
        """Existe et n'est pas personnelle (le propriétaire d'une équipe personnelle est unique :
        la validation des plans remonte la chaîne `invited_by` depuis lui)."""
        found = await conn.execute(sa.select(t.teams.c.personal).where(t.teams.c.id == team_id))
        row = found.first()
        if row is None:
            raise NotFound("équipe introuvable")
        if row.personal:
            raise PersonalTeam("équipe personnelle")


class _Tx:
    """Transaction : erreurs de stockage opaques, doublons traduits en `Conflict`."""

    def __init__(self, engine: AsyncEngine, operation: str) -> None:
        self._ctx = engine.begin()
        self._operation = operation

    async def __aenter__(self) -> AsyncConnection:
        try:
            return await self._ctx.__aenter__()
        except SQLAlchemyError as exc:
            log_failure(self._operation, exc)
            raise StoreError("stockage indisponible") from None

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            await self._ctx.__aexit__(exc_type, exc, tb)
        except IntegrityError:
            raise Conflict("doublon") from None
        except SQLAlchemyError as caught:
            log_failure(self._operation, caught)
            raise StoreError("stockage indisponible") from None
        if isinstance(exc, IntegrityError):
            raise Conflict("doublon") from None
        if isinstance(exc, SQLAlchemyError):
            log_failure(self._operation, exc)
            raise StoreError("stockage indisponible") from None
