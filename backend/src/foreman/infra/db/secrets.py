"""Secrets chiffrés en PostgreSQL : seul `SealedSecret` touche la base, jamais le texte clair."""

from collections.abc import Callable

import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.core.store import StoreError
from foreman.infra.db import tables as t
from foreman.infra.db.engine import log_failure
from foreman.infra.secrets import Keyring, SealedSecret, open_sealed, seal

_S = t.secrets


class PostgresSecretStore:
    def __init__(self, engine: AsyncEngine, ring: Callable[[], Keyring]) -> None:
        self._engine = engine
        self._ring = ring  # relu à chaque appel : une rotation par la CLI est vue sans redémarrage

    async def put(self, secret_id: str, kind: str, value: SecretStr, *, created_by: str) -> None:
        sealed = seal(self._ring(), secret_id, kind, value)
        values = {
            "kind": kind,
            "key_id": sealed.key_id,
            "nonce": sealed.nonce,
            "ciphertext": sealed.ciphertext,
            "created_by": created_by,
        }
        stmt = insert(_S).values(id=secret_id, **values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[_S.c.id],
            set_={**values, "created_at": sa.func.now(), "rotated_at": None},
        )
        await self._execute("secrets.put", stmt)

    async def get(self, secret_id: str, kind: str) -> SecretStr | None:
        try:
            async with self._engine.connect() as conn:
                row = (await conn.execute(sa.select(_S).where(_S.c.id == secret_id))).first()
        except SQLAlchemyError as exc:
            log_failure("secrets.get", exc)
            raise StoreError("stockage indisponible") from None
        if row is None:
            return None
        # `kind` vient de l'appelant : s'il diffère de la ligne, l'AAD ne correspond pas (refus).
        return open_sealed(
            self._ring(), secret_id, kind, SealedSecret(row.key_id, row.nonce, row.ciphertext)
        )

    async def delete(self, secret_id: str) -> bool:
        stmt = sa.delete(_S).where(_S.c.id == secret_id).returning(_S.c.id)
        return await self._execute("secrets.delete", stmt) == 1

    async def exists(self, secret_id: str) -> bool:
        return (
            await self._execute("secrets.exists", sa.select(_S.c.id).where(_S.c.id == secret_id))
            == 1
        )

    async def rotate(self) -> int:
        """Rechiffre, dans une transaction, les lignes qui ne sont pas sous la clé active."""
        ring = self._ring()
        try:
            async with self._engine.begin() as conn:
                rows = (
                    await conn.execute(
                        sa.select(_S).where(_S.c.key_id != ring.active).with_for_update()
                    )
                ).all()
                for row in rows:
                    old = SealedSecret(row.key_id, row.nonce, row.ciphertext)
                    new = seal(ring, row.id, row.kind, open_sealed(ring, row.id, row.kind, old))
                    await conn.execute(
                        sa.update(_S)
                        .where(_S.c.id == row.id)
                        .values(
                            key_id=new.key_id,
                            nonce=new.nonce,
                            ciphertext=new.ciphertext,
                            rotated_at=sa.func.now(),
                        )
                    )
        except SQLAlchemyError as exc:
            log_failure("secrets.rotate", exc)
            raise StoreError("stockage indisponible") from None
        return len(rows)

    async def _execute(self, operation: str, stmt: sa.Executable) -> int:
        """Exécute `stmt` et renvoie le nombre de lignes produites (ou touchées)."""
        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(stmt)
                return len(result.all()) if result.returns_rows else result.rowcount
        except SQLAlchemyError as exc:
            log_failure(operation, exc)
            raise StoreError("stockage indisponible") from None
