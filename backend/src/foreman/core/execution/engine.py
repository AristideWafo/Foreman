"""Moteur d'exécution : une exécution approuvée, étape par étape, uniquement par la gateway.

Pour chaque étape non réussie : renouveler le bail, réserver la clé d'idempotence, résoudre les
références `$from`, appeler la gateway, puis écrire étape, registre et audit dans UNE transaction
(`complete_step`). Un bail perdu arrête le moteur sans rien écrire. Tout échec (refus, échec
d'outil, réservation orpheline, exception inattendue) finit l'exécution en `blocked`.

Rien de ce qui vient d'une exception, d'un paramètre ou d'un adaptateur n'entre dans un événement
ou un journal : seuls des codes fixes et des numéros d'étape sortent.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from typing import Final, cast
from uuid import UUID, uuid4

from pydantic import JsonValue

from foreman.core.catalog import Catalog
from foreman.core.events import EventData, ExecutionLogData, ExecutionStepData, StepStatus
from foreman.core.execution.cards import execution_card, execution_card_id
from foreman.core.gateway.errors import CallDenied, GatewayError
from foreman.core.gateway.port import Gateway, GatewayCall, GatewayResult
from foreman.core.ports import EventLog
from foreman.core.references import UnresolvedReference, resolve_params
from foreman.core.store import (
    AuditEntry,
    CompletedReservation,
    ExecutionRecord,
    Lease,
    NewReservation,
    OrphanReservation,
    PlanRecord,
    StaleLease,
    StepRecord,
    Stores,
)

log = logging.getLogger(__name__)

OWNER_PREFIX: Final = "engine"
RESUME_CLAIM_ATTEMPTS: Final = 15  # le bail d'un processus tué reste valide jusqu'à 60 s
RESUME_CLAIM_DELAY_S: Final = 5.0
IN_PROGRESS_ATTEMPTS: Final = 5  # `call_in_progress` : le même appel tourne encore
IN_PROGRESS_DELAY_S: Final = 1.0


class _Blocked(Exception):
    """Interne : l'exécution doit finir `blocked`. `seq` : étape en cause, si elle est connue."""

    def __init__(self, seq: int | None = None) -> None:
        super().__init__("blocked")
        self.seq = seq


class _LeaseLost(Exception):
    """Interne : un autre travailleur tient l'exécution ; on s'arrête sans rien écrire."""


class ExecutionEngine:
    def __init__(
        self,
        *,
        catalog: Catalog,
        stores: Stores,
        gateway: Gateway,
        events: EventLog,
        clock: Callable[[], float] = time.monotonic,
        resume_claim_attempts: int = RESUME_CLAIM_ATTEMPTS,
        resume_claim_delay_s: float = RESUME_CLAIM_DELAY_S,
    ) -> None:
        self._catalog = catalog
        self._stores = stores
        self._gateway = gateway
        self._events = events
        self._clock = clock
        self._resume_attempts = resume_claim_attempts
        self._resume_delay_s = resume_claim_delay_s

    async def run(self, project_id: UUID, execution_id: UUID, *, resumed: bool = False) -> None:
        """Mène l'exécution à son terme. Ne lève jamais (sauf annulation de la tâche).

        `resumed` : reprise au démarrage. La carte d'exécution est alors réémise d'abord (le flux
        du chat est vide après un redémarrage) et la prise du bail est retentée un temps borné.
        """
        owner = f"{OWNER_PREFIX}-{uuid4().hex[:12]}"  # un propriétaire par run : le bail exclut
        lease = await self._claim(execution_id, owner, resumed)
        if lease is None:
            return
        started = self._clock()
        try:
            if resumed:
                await self._emit_card(project_id, execution_id, started)
            await self._drive(lease, project_id, started)
            await self._finish(lease, project_id, started)
        except _LeaseLost:
            log.info("execution %s : bail perdu, arrêt", execution_id)
        except StaleLease:
            log.info("execution %s : bail perdu, arrêt", execution_id)
        except _Blocked as blocked:
            await self._block(lease, project_id, blocked.seq, started)
        except Exception as exc:
            log.warning("execution %s : défaut (%s)", execution_id, type(exc).__name__)
            await self._block(lease, project_id, None, started)

    # --- Prise du bail -------------------------------------------------------------------------

    async def _claim(self, execution_id: UUID, owner: str, resumed: bool) -> Lease | None:
        attempts = self._resume_attempts if resumed else 1
        for attempt in range(1, attempts + 1):
            try:
                lease = await self._stores.executions.claim_lease(execution_id, owner)
            except Exception as exc:
                log.warning("execution %s : bail illisible (%s)", execution_id, type(exc).__name__)
                return None
            if lease is not None:
                return lease
            if attempt < attempts:
                await asyncio.sleep(self._resume_delay_s)
        return None

    # --- Boucle d'étapes -----------------------------------------------------------------------

    async def _drive(self, lease: Lease, project_id: UUID, started: float) -> None:
        execution = await self._stores.executions.get(project_id, lease.execution_id)
        if execution is None:
            raise _Blocked
        plan = await self._stores.plans.get(project_id, execution.plan_id)
        if plan is None:
            raise _Blocked
        outputs = _outputs(execution)
        while (step := await self._stores.executions.next_step(lease.execution_id)) is not None:
            if not await self._stores.executions.renew(lease):
                raise _LeaseLost
            await self._run_step(lease, project_id, plan, step, outputs, started)

    async def _run_step(
        self,
        lease: Lease,
        project_id: UUID,
        plan: PlanRecord,
        step: StepRecord,
        outputs: dict[int, Mapping[str, JsonValue]],
        started: float,
    ) -> None:
        stores = self._stores
        reservation = await stores.executions.reserve_idempotency(lease, step.seq)
        if isinstance(reservation, OrphanReservation):
            raise _Blocked(step.seq)  # réservée sans résultat : jamais rejouée à l'aveugle
        if isinstance(reservation, CompletedReservation):
            # La clé a déjà abouti : on reprend son résultat, rien n'est rappelé.
            result = cast(Mapping[str, JsonValue], reservation.result)
            replay = AuditEntry(
                actor_kind="engine",
                project_id=project_id,
                plan_id=plan.id,
                execution_id=lease.execution_id,
                step_seq=step.seq,
                plan_hash=plan.content_hash,
                tool=step.tool,
                decision="replayed",
                result_redacted=dict(reservation.result),
            )
            await stores.executions.complete_step(lease, step.seq, result, [], [replay])
            outputs[step.seq] = result
            await self._step_event(project_id, lease.execution_id, step.seq, "succeeded")
            await self._emit_card(project_id, lease.execution_id, started)
            return
        assert isinstance(reservation, NewReservation)  # noqa: S101 - union fermée
        await self._step_event(project_id, lease.execution_id, step.seq, "running")
        try:
            params = resolve_params(cast(Mapping[str, JsonValue], step.params), outputs, step.seq)
            result_ = await self._call(lease, project_id, plan, step, params)
        except UnresolvedReference:
            raise _Blocked(step.seq) from None
        except _LeaseLost:
            raise
        except GatewayError as error:
            log.warning(
                "execution %s : étape %d refusée (%s)", lease.execution_id, step.seq, error.code
            )
            raise _Blocked(step.seq) from None
        except Exception as exc:
            log.warning(
                "execution %s : défaut à l'étape %d (%s)",
                lease.execution_id,
                step.seq,
                type(exc).__name__,
            )
            raise _Blocked(step.seq) from None
        await stores.executions.complete_step(
            lease, step.seq, result_.output, list(result_.resources), [result_.audit]
        )
        outputs[step.seq] = result_.output
        if result_.logs:
            card_id = execution_card_id(lease.execution_id)
            await self._emit(
                project_id,
                lease.execution_id,
                ExecutionLogData(card_id=card_id, step=step.seq, lines=result_.logs),
            )
        await self._step_event(project_id, lease.execution_id, step.seq, "succeeded")
        await self._emit_card(project_id, lease.execution_id, started)

    async def _call(
        self,
        lease: Lease,
        project_id: UUID,
        plan: PlanRecord,
        step: StepRecord,
        params: Mapping[str, JsonValue],
    ) -> GatewayResult:
        """Appel de la gateway. `stale_lease` : on s'arrête sans bloquer (un autre worker a pris
        la suite). `call_in_progress` : le même appel tourne encore, on réessaie un temps borné."""
        call = GatewayCall(
            project_id=project_id,
            execution_id=lease.execution_id,
            step_seq=step.seq,
            plan_hash=plan.content_hash,
            tool=step.tool,
            params=params,
            idempotency_key=step.idempotency_key,
            lease_owner=lease.owner,
            lease_epoch=lease.epoch,
        )
        for attempt in range(1, IN_PROGRESS_ATTEMPTS + 1):
            try:
                return await self._gateway.call(call)
            except CallDenied as denied:
                if denied.code == "stale_lease":
                    raise _LeaseLost from None
                if denied.code != "call_in_progress" or attempt == IN_PROGRESS_ATTEMPTS:
                    raise
                await asyncio.sleep(IN_PROGRESS_DELAY_S)
        raise _Blocked(step.seq)  # inatteignable : la boucle rend ou lève

    # --- Fin -----------------------------------------------------------------------------------

    async def _finish(self, lease: Lease, project_id: UUID, started: float) -> None:
        await self._stores.executions.finish(lease, "succeeded")
        await self._emit_card(project_id, lease.execution_id, started)

    async def _block(self, lease: Lease, project_id: UUID, seq: int | None, started: float) -> None:
        try:
            await self._stores.executions.finish(lease, "blocked")
        except Exception as exc:
            log.warning(
                "execution %s : blocage non écrit (%s)", lease.execution_id, type(exc).__name__
            )
            return
        if seq is not None:
            await self._step_event(project_id, lease.execution_id, seq, "failed")
        await self._emit_card(project_id, lease.execution_id, started)

    # --- Événements (turn_id = execution_id) ---------------------------------------------------

    async def _emit(self, project_id: UUID, execution_id: UUID, data: EventData) -> None:
        try:
            await self._events.append(project_id, execution_id, data)
        except Exception as exc:  # un flux défaillant ne doit jamais changer l'issue
            log.warning("execution %s : événement perdu (%s)", execution_id, type(exc).__name__)

    async def _step_event(
        self, project_id: UUID, execution_id: UUID, seq: int, status: StepStatus
    ) -> None:
        data = ExecutionStepData(card_id=execution_card_id(execution_id), step=seq, status=status)
        await self._emit(project_id, execution_id, data)

    async def _emit_card(self, project_id: UUID, execution_id: UUID, started: float) -> None:
        try:
            card = await execution_card(
                self._stores,
                self._catalog,
                project_id,
                execution_id,
                int(self._clock() - started),
            )
        except Exception as exc:
            log.warning("execution %s : carte illisible (%s)", execution_id, type(exc).__name__)
            return
        if card is not None:
            await self._emit(project_id, execution_id, card)


def _outputs(execution: ExecutionRecord) -> dict[int, Mapping[str, JsonValue]]:
    return {
        s.seq: cast(Mapping[str, JsonValue], s.result)
        for s in execution.steps
        if s.status == "succeeded" and s.result is not None
    }
