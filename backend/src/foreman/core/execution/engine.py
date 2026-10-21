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
from dataclasses import replace
from typing import Final, cast
from uuid import UUID, uuid4

from pydantic import JsonValue

from foreman.core.catalog import Catalog
from foreman.core.events import (
    DiagnosticCardData,
    EventData,
    ExecutionDiagnosticData,
    ExecutionLogData,
    ExecutionStepData,
    StepStatus,
)
from foreman.core.execution.cards import execution_card, execution_card_id
from foreman.core.gateway.errors import CallDenied, CallFailed, GatewayError
from foreman.core.gateway.port import Gateway, GatewayCall, GatewayResult
from foreman.core.ports import EventLog, RawLogStore
from foreman.core.references import UnresolvedReference, resolve_params
from foreman.core.store import (
    AuditEntry,
    CompletedReservation,
    ExecutionRecord,
    InvalidTransition,
    Lease,
    NewReservation,
    OrphanReservation,
    PlanRecord,
    Reservation,
    StaleLease,
    StepRecord,
    Stores,
    TakenOverReservation,
)

log = logging.getLogger(__name__)

OWNER_PREFIX: Final = "engine"
RESUME_CLAIM_ATTEMPTS: Final = 15  # le bail d'un processus tué reste valide jusqu'à 60 s
RESUME_CLAIM_DELAY_S: Final = 5.0
IN_PROGRESS_ATTEMPTS: Final = 5  # `call_in_progress` : le même appel tourne encore
IN_PROGRESS_DELAY_S: Final = 1.0
LEASE_RENEW_INTERVAL_S: Final = 20.0  # un tiers du bail (60 s) : renouvelé pendant un appel long
# Sans code connu, le modèle ne devine pas : une carte « diagnostic requis » appelle l'humain.
HUMAN_FALLBACK_CODES: Final = frozenset({"unknown", "adapter_error"})
SHUTDOWN_GRACE_S: Final = 8.0  # sous les 10 s de `docker stop` par défaut (voir `shutdown`)


class _Blocked(Exception):
    """Interne : l'exécution doit finir `blocked`. `seq` : étape en cause, si elle est connue."""

    def __init__(self, seq: int | None = None) -> None:
        super().__init__("blocked")
        self.seq = seq


class _LeaseLost(Exception):
    """Interne : un autre travailleur tient l'exécution ; on s'arrête sans rien écrire."""


class _Stopped(Exception):
    """Interne : arrêt demandé (`shutdown`) ; on ne prend plus d'étape, on libère le bail."""


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
        lease_renew_interval_s: float = LEASE_RENEW_INTERVAL_S,
        raw_logs: RawLogStore | None = None,
    ) -> None:
        self._catalog = catalog
        self._stores = stores
        self._gateway = gateway
        self._events = events
        self._raw_logs = raw_logs
        self._clock = clock
        self._resume_attempts = resume_claim_attempts
        self._resume_delay_s = resume_claim_delay_s
        self._renew_interval_s = lease_renew_interval_s
        self._stopping = False
        self._active: set[asyncio.Task[None]] = set()

    async def shutdown(self, grace_s: float = SHUTDOWN_GRACE_S) -> None:
        """Arrêt propre : plus aucune étape n'est prise, l'appel en cours peut se terminer.

        Borné par `grace_s` ; au-delà, l'appelant annule les tâches et chaque étape coupée
        libère sa réservation (`release`). Le délai de grâce d'uvicorn (5 s dans le Dockerfile)
        est plus court que `timeout_s` de certains outils (900 s pour `apply_playbook`) : un
        appel plus long que le délai est coupé, puis rejoué à la reprise (clé d'idempotence).
        """
        self._stopping = True
        pending = [t for t in self._active if not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=grace_s)

    async def run(self, project_id: UUID, execution_id: UUID, *, resumed: bool = False) -> None:
        """Mène l'exécution à son terme. Ne lève jamais (sauf annulation de la tâche).

        `resumed` : reprise au démarrage. La carte d'exécution est alors réémise d'abord (le flux
        du chat est vide après un redémarrage) et la prise du bail est retentée un temps borné.
        """
        if self._stopping:
            return
        task = asyncio.current_task()
        if task is not None:
            self._active.add(task)
        try:
            await self._run(project_id, execution_id, resumed)
        finally:
            if task is not None:
                self._active.discard(task)

    async def _run(self, project_id: UUID, execution_id: UUID, resumed: bool) -> None:
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
        except _Stopped:
            await self._release(lease, None)
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
                return replace(lease, key_suffix=self._gateway.idempotency_scope)
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
            if self._stopping:
                raise _Stopped
            if not await self._stores.executions.renew(lease):
                raise _LeaseLost
            try:
                await self._run_step(lease, project_id, plan, step, outputs, started)
            except Exception as exc:
                if isinstance(exc, _Blocked | _LeaseLost | StaleLease):
                    raise
                # Défaut de stockage ou autre : on bloque en désignant l'étape en cause.
                log.warning(
                    "execution %s : défaut à l'étape %d (%s)",
                    lease.execution_id,
                    step.seq,
                    type(exc).__name__,
                )
                raise _Blocked(step.seq) from None

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
        reservation: (
            Reservation | TakenOverReservation
        ) = await stores.executions.reserve_idempotency(lease, step.seq)
        if isinstance(reservation, OrphanReservation):
            # Réservée sans résultat : rejouée seulement si l'outil se rappelle sans risque.
            if not self._replayable(step.tool):
                raise _Blocked(step.seq)
            try:
                reservation = await stores.executions.take_over(lease, step.seq)
            except InvalidTransition:
                # Course bénigne (ancien propriétaire libéré) : une seule nouvelle réservation.
                reservation = await stores.executions.reserve_idempotency(lease, step.seq)
                if isinstance(reservation, OrphanReservation):
                    raise _Blocked(step.seq) from None
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
                rule_id="engine-replay",
                result_redacted=dict(reservation.result),
            )
            await stores.executions.complete_step(lease, step.seq, result, [], [replay])
            outputs[step.seq] = result
            await self._step_event(project_id, lease.execution_id, step.seq, "succeeded")
            await self._emit_card(project_id, lease.execution_id, started)
            return
        assert isinstance(reservation, NewReservation | TakenOverReservation)  # noqa: S101 - union fermée
        try:
            await self._execute(lease, project_id, plan, step, outputs, started)
        except asyncio.CancelledError:
            # Annulation (arrêt du serveur) : la réservation ne reste pas orpheline. Si l'effet a
            # peut-être eu lieu, le rejeu est sûr : l'adaptateur est idempotent sur la clé.
            await asyncio.shield(asyncio.ensure_future(self._release(lease, step.seq)))
            raise

    async def _execute(
        self,
        lease: Lease,
        project_id: UUID,
        plan: PlanRecord,
        step: StepRecord,
        outputs: dict[int, Mapping[str, JsonValue]],
        started: float,
    ) -> None:
        stores = self._stores
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
            if isinstance(error, CallFailed) and error.diagnostic is not None:
                # Le modèle lira ce diagnostic typé à son prochain tour (jamais un log brut).
                await self._emit(
                    project_id,
                    lease.execution_id,
                    ExecutionDiagnosticData(
                        card_id=execution_card_id(lease.execution_id),
                        step=step.seq,
                        tool=step.tool,
                        diagnostic=error.diagnostic,
                    ),
                )
                if error.diagnostic.code in HUMAN_FALLBACK_CODES:
                    await self._ask_human(project_id, lease.execution_id, step, error)
            if isinstance(error, CallDenied) and error.code != "call_in_progress":
                # Refus avant effet : la clé ne doit pas rester orpheline pour un plan identique.
                await self._release(lease, step.seq, keep_lease=True)
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

    async def _ask_human(
        self, project_id: UUID, execution_id: UUID, step: StepRecord, error: CallFailed
    ) -> None:
        """Carte « diagnostic requis » : extrait masqué au flux, log brut gardé côté serveur."""
        assert error.diagnostic is not None  # noqa: S101 - vérifié par l'appelant
        kept = False
        if self._raw_logs is not None and error.raw_logs:
            self._raw_logs.put(project_id, execution_id, step.seq, error.raw_logs)
            kept = True
        card = DiagnosticCardData(
            card_id=f"diagnostic-{execution_id}-{step.seq}",
            kind="diagnostic",
            execution_id=execution_id,
            step=step.seq,
            tool=step.tool,
            extract=error.diagnostic.extract or [],
            raw_log_available=kept,
        )
        await self._emit(project_id, execution_id, card)

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
                return await self._call_leased(lease, call)
            except CallDenied as denied:
                if denied.code == "stale_lease":
                    raise _LeaseLost from None
                if denied.code != "call_in_progress" or attempt == IN_PROGRESS_ATTEMPTS:
                    raise
                await asyncio.sleep(IN_PROGRESS_DELAY_S)
        raise _Blocked(step.seq)  # inatteignable : la boucle rend ou lève

    async def _call_leased(self, lease: Lease, call: GatewayCall) -> GatewayResult:
        """Appel de la gateway pendant lequel le bail est renouvelé en tâche de fond.

        Si le renouvellement échoue (bail repris), l'appel est annulé et le moteur s'arrête.
        """
        call_task = asyncio.ensure_future(self._gateway.call(call))
        beat = asyncio.ensure_future(self._heartbeat(lease))
        try:
            await asyncio.wait({call_task, beat}, return_when=asyncio.FIRST_COMPLETED)
            if not call_task.done():
                raise _LeaseLost
            return call_task.result()
        finally:
            beat.cancel()
            call_task.cancel()
            await asyncio.gather(beat, call_task, return_exceptions=True)

    async def _heartbeat(self, lease: Lease) -> None:
        """Rend la main (donc annule l'appel) dès que le bail ne peut plus être renouvelé."""
        while True:
            await asyncio.sleep(self._renew_interval_s)
            try:
                if not await self._stores.executions.renew(lease):
                    return
            except Exception:
                return

    def _replayable(self, tool: str) -> bool:
        """Outil de lecture ou déclaré idempotent au catalogue : rappelé sans risque (D3)."""
        definition = self._catalog.tools.get(tool)
        return definition is not None and (
            definition.tool_class == "read" or definition.idempotency is not None
        )

    async def _release(
        self, lease: Lease, step_seq: int | None, *, keep_lease: bool = False
    ) -> None:
        try:
            await self._stores.executions.release(lease, step_seq, keep_lease=keep_lease)
        except Exception as exc:
            log.warning(
                "execution %s : libération non écrite (%s)", lease.execution_id, type(exc).__name__
            )

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
