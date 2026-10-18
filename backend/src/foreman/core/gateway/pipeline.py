"""Tool Gateway : le seul chemin entre le moteur et un adaptateur.

Dix étapes, dans cet ordre, chacune ne pouvant que refuser :
1 contexte (exécution en cours, bail valide, étape réservée), 2 outil connu, 3 schéma, 4 matrice,
5 approbations, 6 invariants et périmètre, 7 budget, 8 exécution (avec délai), 9 filtrage de la
sortie, 10 audit.

Audit : une ligne `allow` est écrite AVANT l'exécution (la décision) ; un refus ou un échec écrit
sa propre ligne (`denied`, `error`) ; l'appel exécuté rend sa ligne de résultat (`executed`) au
moteur, qui l'écrit avec l'étape (`complete_step`). Rien de ce qui vient du modèle, des paramètres
ou d'un adaptateur n'entre dans une erreur ou un journal : seuls des codes fixes sortent, et les
erreurs sont levées HORS des blocs `except` (aucune exception d'origine ne reste attachée).
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, cast
from urllib.parse import urlsplit
from uuid import UUID

from jsonschema import Draft202012Validator
from pydantic import JsonValue

from foreman.core.catalog import Catalog, ToolDefinition
from foreman.core.gateway.budget import CallBudget
from foreman.core.gateway.errors import CallDenied, CallFailed, DenialCode, FailureCode
from foreman.core.gateway.port import GatewayCall, GatewayResult
from foreman.core.gateway.redact import (
    MAX_OUTPUT_BYTES,
    bounded_for_audit,
    filter_logs,
    json_size,
    mask_text,
    redact_value,
    truncated_output,
)
from foreman.core.gateway.scope import in_scope
from foreman.core.policy.matrix import (
    Allow,
    AllowIf,
    Deny,
    PolicyRequest,
    effective_level,
    evaluate,
)
from foreman.core.ports import (
    AdapterError,
    AdapterResult,
    ForeignResource,
    PermissionMissing,
    ToolAdapter,
)
from foreman.core.references import UnresolvedReference, resolve_params
from foreman.core.store import (
    MAX_AUDIT_DURATION_MS,
    AuditEntry,
    ExecutionRecord,
    Lease,
    NewResource,
    PlanRecord,
    StepRecord,
    StoreError,
    Stores,
)

log = logging.getLogger(__name__)

# Pas encore de rôles ni d'authentification (semaine 10) : le développeur valide son propre plan.
DEFAULT_ROLE: Final = "developer"
ACTOR_KIND: Final = "engine"
MAX_TOOL_NAME_AUDIT: Final = 100
MAX_EXTERNAL_ID: Final = 200
# Un outil appelé avec `mode: check` ne crée rien : il n'inscrit aucune ressource au registre.
DRY_RUN_PARAM: Final = "mode"
DRY_RUN_VALUE: Final = "check"


class _Refusal(Exception):
    """Interne : un contrôle refuse l'appel. Jamais exposé (converti en `CallDenied`)."""

    def __init__(self, code: DenialCode, rule_id: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.rule_id = rule_id


@dataclass(slots=True)
class _Trace:
    """Ce que l'audit saura de l'appel, rempli au fil des étapes."""

    plan_id: UUID | None = None
    plan_hash: str | None = None
    tool: ToolDefinition | None = None
    rule_id: str | None = None


@dataclass(frozen=True, slots=True)
class _Authorized:
    tool: ToolDefinition
    verdict: Allow | AllowIf


def _canonical(value: object) -> str:
    """JSON canonique : distingue `1` de `true` et ne dépend pas de l'ordre des clés."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _identifier(value: JsonValue | None) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int | str):
        return None
    text = str(value)
    return text if text and len(text) <= MAX_EXTERNAL_ID else None


def safe_url(value: object) -> str | None:
    """URL http(s) sans identifiants, sans paramètres ni ancre ; sinon `None`."""
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    return f"{parts.scheme}://{host}{port}{parts.path}"


def _valid_result(raw: object) -> AdapterResult | None:
    """Forme du résultat d'un adaptateur (zone non fiable), normalisée en JSON pur.

    La normalisation (`dumps` puis `loads`) transforme les tuples en listes et les clés en chaînes :
    plus rien d'exotique n'atteint le masquage, l'audit ni la sérialisation. Une valeur qui n'est
    pas du JSON (ensemble, octets, `nan`, clé étrangère) donne `None`.
    """
    if not isinstance(raw, AdapterResult):
        return None
    if not isinstance(raw.logs, list) or not all(isinstance(line, str) for line in raw.logs):
        return None
    try:
        output = json.loads(json.dumps(raw.output, allow_nan=False))
    except (TypeError, ValueError, RecursionError):
        return None
    if not isinstance(output, dict):
        return None
    return AdapterResult(output=output, logs=list(raw.logs))


class ToolGateway:
    def __init__(
        self,
        *,
        catalog: Catalog,
        stores: Stores,
        adapters: Mapping[str, ToolAdapter],
        role: str = DEFAULT_ROLE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        missing = {t.connector for t in catalog.tools.values()} - set(adapters)
        if missing:
            raise ValueError(f"connecteur sans adaptateur : {sorted(missing)}")
        self._catalog = catalog
        self._stores = stores
        self._adapters = adapters
        self._role = role
        self._clock = clock
        budget = catalog.policy.budgets.per_execution
        self._budget = CallBudget(budget.max_tool_calls, budget.max_minutes * 60.0, clock)
        self._validators = {
            name: Draft202012Validator(tool.input) for name, tool in catalog.tools.items()
        }
        self._inflight: set[tuple[UUID, int]] = set()

    async def call(self, call: GatewayCall) -> GatewayResult:
        key = (call.execution_id, call.step_seq)
        started = self._clock()
        trace = _Trace()
        # Aucun point de suspension entre le test et l'ajout : deux appels simultanés de la même
        # étape ne lancent jamais l'adaptateur deux fois (et ne comptent qu'une fois au budget).
        if key in self._inflight:
            await self._audit(call, trace, "denied", "call_in_progress", None, started)
            raise CallDenied("call_in_progress")
        self._inflight.add(key)
        try:
            return await self._run(call, trace, started)
        finally:
            self._inflight.discard(key)

    async def _run(self, call: GatewayCall, trace: _Trace, started: float) -> GatewayResult:
        denial: DenialCode | None = None
        failure: FailureCode = "internal_error"
        rule_id: str | None = None
        try:
            authorized = await self._authorize(call, trace)
            try:
                await self._record_decision(call, trace, authorized, started)
            except BaseException:
                self._budget.refund(call.execution_id)  # rien ne s'exécutera : appel non compté
                raise
            return await self._execute(call, trace, authorized, started)
        except _Refusal as refusal:
            denial, rule_id = refusal.code, refusal.rule_id
        except CallFailed as failed:
            failure, rule_id = cast(FailureCode, failed.code), trace.rule_id
        except StoreError:
            log.warning("gateway : stockage indisponible (étape %d)", call.step_seq)
            failure, rule_id = "storage_unavailable", trace.rule_id
        except Exception as exc:
            # Défaut inattendu (registre, store, bogue) : seul le type est journalisé.
            log.warning("gateway : exception inattendue (%s)", type(exc).__name__)
            failure, rule_id = "internal_error", trace.rule_id
        except BaseException as exc:
            # Annulation (arrêt, délai du moteur) : la décision est déjà en audit, on y ajoute
            # l'issue puis on relance.
            code = "cancelled" if isinstance(exc, asyncio.CancelledError) else "interrupted"
            await asyncio.shield(self._audit(call, trace, "error", code, trace.rule_id, started))
            raise
        if denial is not None:
            await self._audit(call, trace, "denied", denial, rule_id, started)
            raise CallDenied(denial)
        await self._audit(call, trace, "error", failure, rule_id, started)
        raise CallFailed(failure)

    # --- Étapes 1 à 7 : décider --------------------------------------------------------------

    async def _authorize(self, call: GatewayCall, trace: _Trace) -> _Authorized:
        execution, plan, step = await self._context(call, trace)  # 1
        tool = self._catalog.tools.get(call.tool)  # 2
        if tool is None:
            raise _Refusal("unknown_tool")
        trace.tool = tool
        if not self._validators[tool.tool].is_valid(call.params):  # 3
            raise _Refusal("invalid_params")
        environment = plan.content.get("environment")  # 4
        if not isinstance(environment, str):
            raise _Refusal("unknown_context")
        matrix = self._catalog.policy
        verdict = evaluate(
            matrix,
            PolicyRequest(
                tool_class=tool.tool_class,
                environment=environment,
                reversibility=tool.effective_reversibility(call.params),
                role=self._role,
                level=effective_level(matrix, environment, execution.autonomy_level),
            ),
        )
        if isinstance(verdict, Deny):
            raise _Refusal("policy_denied", verdict.rule_id)
        trace.rule_id = verdict.rule_id
        # Seule l'approbation du développeur existe : un environnement qui exige un administrateur
        # n'autorise aucune écriture (la lecture, `Allow`, reste permise).
        if isinstance(verdict, AllowIf) and (
            matrix.autonomy.environments[environment].admin_approval_required
        ):
            raise _Refusal("policy_denied", verdict.rule_id)
        self._check_approval(call, plan, execution, step, verdict)  # 5
        await self._check_invariants(call, tool, environment)  # 6
        if not self._budget.consume(call.execution_id):  # 7
            raise _Refusal("budget_exceeded", verdict.rule_id)
        return _Authorized(tool, verdict)

    async def _context(
        self, call: GatewayCall, trace: _Trace
    ) -> tuple[ExecutionRecord, PlanRecord, StepRecord]:
        execution = await self._stores.executions.get(call.project_id, call.execution_id)
        if execution is None or execution.state != "running":
            raise _Refusal("unknown_context")
        plan = await self._stores.plans.get(call.project_id, execution.plan_id)
        step = next((s for s in execution.steps if s.seq == call.step_seq), None)
        if plan is None or step is None:
            raise _Refusal("unknown_context")
        trace.plan_id, trace.plan_hash = plan.id, plan.content_hash
        # Le bail doit être celui de l'appelant ici et maintenant (propriétaire et époque).
        lease = Lease(call.execution_id, call.lease_owner, call.lease_epoch)
        if not await self._stores.executions.renew(lease):
            raise _Refusal("stale_lease")
        # L'étape a été réservée (`running`) et les précédentes ont réussi : pas de rejeu d'une
        # étape terminée, pas d'étape sautée.
        if step.status != "running" or any(
            s.seq < step.seq and s.status != "succeeded" for s in execution.steps
        ):
            raise _Refusal("step_not_ready")
        return execution, plan, step

    @staticmethod
    def _check_approval(
        call: GatewayCall,
        plan: PlanRecord,
        execution: ExecutionRecord,
        step: StepRecord,
        verdict: Allow | AllowIf,
    ) -> None:
        if plan.status != "dev_approved":
            raise _Refusal("plan_not_approved", verdict.rule_id)
        if call.plan_hash != plan.content_hash:
            raise _Refusal("plan_hash_mismatch", verdict.rule_id)
        outputs = {
            s.seq: cast(Mapping[str, JsonValue], s.result)
            for s in execution.steps
            if s.status == "succeeded" and s.result
        }
        try:
            expected = resolve_params(cast(Mapping[str, JsonValue], step.params), outputs, step.seq)
        except UnresolvedReference:
            raise _Refusal("call_differs_from_step", verdict.rule_id) from None
        if (
            call.tool != step.tool
            or call.idempotency_key != step.idempotency_key
            or _canonical(dict(call.params)) != _canonical(expected)
        ):
            raise _Refusal("call_differs_from_step", verdict.rule_id)
        # Seule approbation disponible cette semaine : celle du développeur sur le plan.
        if isinstance(verdict, AllowIf) and not set(verdict.requires) <= {"plan_approved"}:
            raise _Refusal("policy_denied", verdict.rule_id)

    async def _check_invariants(
        self, call: GatewayCall, tool: ToolDefinition, plan_environment: str
    ) -> None:
        if "environment" in call.params and call.params["environment"] != plan_environment:
            raise _Refusal("environment_mismatch")
        allowed = await in_scope(
            catalog=self._catalog,
            registry=self._stores.registry,
            project_id=call.project_id,
            tool=tool,
            params=call.params,
        )
        if not allowed:
            raise _Refusal("scope_violation")

    async def _record_decision(
        self, call: GatewayCall, trace: _Trace, authorized: _Authorized, started: float
    ) -> None:
        """Ligne `allow` AVANT l'exécution : si l'écriture échoue, rien ne s'exécute."""
        tool = authorized.tool
        entry = self._entry(
            call,
            trace,
            "allow",
            authorized.verdict.rule_id,
            started,
            params=bounded_for_audit(call.params, frozenset(tool.redact)),
        )
        await self._stores.audit.append(entry)

    # --- Étapes 8 et 9 : exécuter et filtrer --------------------------------------------------

    async def _invoke(self, call: GatewayCall, tool: ToolDefinition) -> AdapterResult | FailureCode:
        """Appelle l'adaptateur. Rend un code (jamais une exception) : le message d'origine ne
        survit pas."""
        adapter = self._adapters[tool.connector]
        try:
            async with asyncio.timeout(tool.timeout_s):
                raw = await adapter.execute(tool.tool, call.params, call.idempotency_key)
        except TimeoutError:
            return "timeout"
        except PermissionMissing:
            return "permission_missing"
        except ForeignResource:
            return "foreign_resource"
        except AdapterError:
            return "adapter_error"
        except Exception as exc:
            log.warning("gateway : défaut d'adaptateur (%s)", type(exc).__name__)
            return "adapter_defect"
        valid = _valid_result(raw)
        return "invalid_output" if valid is None else valid

    async def _execute(
        self, call: GatewayCall, trace: _Trace, authorized: _Authorized, started: float
    ) -> GatewayResult:
        tool = authorized.tool
        raw = await self._invoke(call, tool)
        if isinstance(raw, str):
            raise CallFailed(raw)
        fields = frozenset(tool.redact)
        resources = self._resources(call, tool, raw.output)
        for (
            resource
        ) in resources:  # une ressource n'a qu'un maître : jamais celle d'un autre projet
            if await self._stores.registry.exists_elsewhere(
                call.project_id, resource.provider, resource.resource_type, resource.external_id
            ):
                raise CallFailed("foreign_resource")
        masked = redact_value(dict(raw.output), fields)
        output = (
            masked
            if isinstance(masked, dict) and json_size(masked) <= MAX_OUTPUT_BYTES
            else truncated_output(masked if isinstance(masked, dict) else {})
        )
        entry = self._entry(
            call,
            trace,
            "executed",
            authorized.verdict.rule_id,
            started,
            params=bounded_for_audit(call.params, fields),
            result=output,
        )
        return GatewayResult(
            output=output, logs=filter_logs(raw.logs), resources=resources, audit=entry
        )

    @staticmethod
    def _resources(
        call: GatewayCall, tool: ToolDefinition, output: Mapping[str, JsonValue]
    ) -> tuple[NewResource, ...]:
        """Ressources CRÉÉES par l'appel, lues sur la sortie brute (le masquage ne doit pas altérer
        l'identifiant). Une mise à jour (portée `update`) ne crée rien."""
        entry = tool.registry
        creates = tool.effective_scope(call.params).kind == "create"
        if entry is None or not creates or call.params.get(DRY_RUN_PARAM) == DRY_RUN_VALUE:
            return ()  # lecture, mise à jour ou essai à blanc : rien n'est créé
        external_id = _identifier(output.get(entry.external_id, call.params.get(entry.external_id)))
        if external_id is None:
            raise CallFailed("invalid_output")
        return (
            NewResource(
                tool.connector, entry.resource_type, external_id, safe_url(output.get("web_url"))
            ),
        )

    # --- Étape 10 : audit ----------------------------------------------------------------------

    def _entry(
        self,
        call: GatewayCall,
        trace: _Trace,
        decision: str,
        rule_id: str | None,
        started: float,
        *,
        params: dict[str, JsonValue] | None = None,
        result: dict[str, JsonValue] | None = None,
    ) -> AuditEntry:
        tool = trace.tool
        elapsed = int((self._clock() - started) * 1000)
        return AuditEntry(
            actor_kind=ACTOR_KIND,
            project_id=call.project_id,
            plan_id=trace.plan_id,
            execution_id=call.execution_id,
            step_seq=call.step_seq,
            plan_hash=trace.plan_hash,
            actor=self._role,
            tool=tool.tool if tool is not None else mask_text(call.tool)[:MAX_TOOL_NAME_AUDIT],
            tool_class=tool.tool_class if tool is not None else None,
            decision=decision,
            rule_id=rule_id,
            params_redacted=params,
            result_redacted=result,
            duration_ms=min(max(elapsed, 0), MAX_AUDIT_DURATION_MS),
        )

    async def _audit(
        self,
        call: GatewayCall,
        trace: _Trace,
        decision: str,
        code: str,
        rule_id: str | None,
        started: float,
    ) -> None:
        """Une ligne par refus ou échec. Si l'écriture échoue, le refus tient quand même."""
        tool = trace.tool
        params = bounded_for_audit(call.params, frozenset(tool.redact)) if tool else None
        entry = self._entry(
            call, trace, decision, rule_id, started, params=params, result={"code": code}
        )
        if code == "unknown_context":
            # Contexte inventé ou étranger : la ligne ne se rattache à aucune exécution réelle.
            entry = _detached(entry)
        try:
            await self._stores.audit.append(entry)
        except Exception as exc:
            # Quelle que soit la panne : le refus tient, seul le type est journalisé.
            log.warning("gateway : audit non écrit (%s, %s)", code, type(exc).__name__)


def _detached(entry: AuditEntry) -> AuditEntry:
    """La même ligne, sans exécution, étape ni plan (pour un contexte inconnu)."""
    return AuditEntry(
        actor_kind=entry.actor_kind,
        project_id=entry.project_id,
        actor=entry.actor,
        tool=entry.tool,
        tool_class=entry.tool_class,
        decision=entry.decision,
        rule_id=entry.rule_id,
        params_redacted=entry.params_redacted,
        result_redacted=entry.result_redacted,
        duration_ms=entry.duration_ms,
    )
