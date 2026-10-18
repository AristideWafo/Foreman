"""Journal d'événements en PostgreSQL : l'historique du chat survit au redémarrage.

Un ajout est UNE transaction : `seq` est pris par `UPDATE projects SET last_event_seq = ... + 1
RETURNING` (la ligne du projet est verrouillée jusqu'à la validation, donc `seq` est contigu même
avec des ajouts concurrents), puis l'insertion, puis l'élagage au-delà de la rétention.

La diffusion aux abonnés se fait après la validation, sous un verrou par projet : l'ordre de
livraison est l'ordre de `seq` (sans lui, `seq` 6 pourrait être livré avant 5 et 5 serait perdu
pour un client qui reprend à 6). Le verrou est local au processus : le direct suppose UN seul
processus (voir docs/PERSISTENCE.md). Aucun appel bloquant : tout passe par le moteur asynchrone.
"""

import asyncio
import weakref
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.core.events import AnyEvent, Event, EventData, make_event
from foreman.core.store import StoreError, UnknownProject
from foreman.infra.db import tables as t
from foreman.infra.db.engine import log_failure
from foreman.infra.subscribers import (
    MAX_SUBSCRIBERS_PER_PROJECT,
    MAX_SUBSCRIBERS_TOTAL,
    SUBSCRIBER_QUEUE_SIZE,
    SubscriberHub,
)

MAX_EVENTS_PER_PROJECT = 1_000  # rétention : les plus anciens sont élagués dans la même transaction

_EVENT: TypeAdapter[AnyEvent] = TypeAdapter(Event)


class PostgresEventLog(SubscriberHub):
    def __init__(
        self,
        engine: AsyncEngine,
        max_events: int = MAX_EVENTS_PER_PROJECT,
        queue_size: int = SUBSCRIBER_QUEUE_SIZE,
        max_subscribers_per_project: int = MAX_SUBSCRIBERS_PER_PROJECT,
        max_subscribers_total: int = MAX_SUBSCRIBERS_TOTAL,
    ) -> None:
        super().__init__(queue_size, max_subscribers_per_project, max_subscribers_total)
        self._engine = engine
        self._max_events = max_events
        # Un verrou par projet, oublié dès que plus personne ne l'attend.
        self._locks: weakref.WeakValueDictionary[UUID, asyncio.Lock] = weakref.WeakValueDictionary()

    async def append(self, project_id: UUID, turn_id: UUID, data: EventData) -> AnyEvent:
        # Protégé de l'annulation : un événement validé en base est toujours diffusé.
        return await asyncio.shield(self._append(project_id, turn_id, data))

    async def _append(self, project_id: UUID, turn_id: UUID, data: EventData) -> AnyEvent:
        lock = self._locks.get(project_id)
        if lock is None:
            lock = self._locks[project_id] = asyncio.Lock()
        async with lock:
            try:
                async with self._engine.begin() as conn:
                    seq = (
                        await conn.execute(
                            sa.update(t.projects)
                            .where(t.projects.c.id == project_id)
                            .values(last_event_seq=t.projects.c.last_event_seq + 1)
                            .returning(t.projects.c.last_event_seq)
                        )
                    ).scalar_one_or_none()
                    if seq is None:
                        raise UnknownProject
                    event = make_event(seq, project_id, turn_id, data)
                    await conn.execute(
                        sa.insert(t.project_events).values(
                            project_id=project_id,
                            seq=seq,
                            turn_id=turn_id,
                            type=event.type,
                            data=event.data.model_dump(mode="json"),
                            at=event.at,
                        )
                    )
                    await conn.execute(
                        sa.delete(t.project_events).where(
                            t.project_events.c.project_id == project_id,
                            t.project_events.c.seq <= seq - self._max_events,
                        )
                    )
            except SQLAlchemyError as exc:
                log_failure("event.append", exc)
                raise StoreError("stockage indisponible") from None
            self._publish(project_id, event)  # sous le verrou : ordre de livraison = ordre de seq
            return event

    async def read_after(self, project_id: UUID, seq: int) -> list[AnyEvent]:
        statement = (
            sa.select(t.project_events)
            .where(t.project_events.c.project_id == project_id, t.project_events.c.seq > seq)
            .order_by(t.project_events.c.seq)
            .limit(self._max_events)
        )
        try:
            async with self._engine.connect() as conn:
                rows = (await conn.execute(statement)).all()
            return [_EVENT.validate_python(_envelope(row)) for row in rows]
        except (SQLAlchemyError, ValidationError) as exc:
            log_failure("event.read_after", exc)
            raise StoreError("stockage indisponible") from None


def _envelope(row: Any) -> dict[str, Any]:
    """Enveloppe v1 reconstruite depuis la ligne (le contrat de l'événement est inchangé)."""
    return {
        "v": 1,
        "seq": row.seq,
        "project_id": row.project_id,
        "turn_id": row.turn_id,
        "at": row.at,
        "type": row.type,
        "data": row.data,
    }
