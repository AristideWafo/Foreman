"""Tool Gateway : le seul chemin entre le moteur et un adaptateur.

Dix étapes, dans cet ordre, chacune ne pouvant que refuser :
1 contexte, 2 outil connu, 3 schéma, 4 matrice, 5 approbations, 6 invariants et périmètre,
7 budget, 8 exécution (avec délai), 9 filtrage de la sortie, 10 audit (une ligne par décision).

Les refus et les échecs sont audités ici ; l'appel exécuté rend sa ligne d'audit au moteur, qui
l'écrit avec l'étape (`complete_step`). Rien de ce qui vient du modèle, des paramètres ou d'un
adaptateur n'entre dans une erreur ou un journal : seuls des codes fixes sortent.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, cast
from uuid import UUID

from jsonschema import Draft202012Validator
from pydantic import JsonValue

from foreman.core.catalog import Catalog, ToolDefinition
from foreman.core.gateway.budget import CallBudget
from foreman.core.gateway.errors import CallDenied, CallFailed, DenialCode
from foreman.core.gateway.port import GatewayCall, GatewayResult
from foreman.core.gateway.redact import (
    MAX_OUTPUT_BYTES,
    bounded_for_audit,
    filter_logs,
    json_size,
    mask_text,
    redact_value,
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
    ForeignResource,
    PermissionMissing,
    ToolAdapter,
)
from foreman.core.references import UnresolvedReference, resolve_params
from foreman.core.store import (
    MAX_AUDIT_DURATION_MS,
    AuditEntry,
    ExecutionRecord,
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

    async def call(self, call: GatewayCall) -> GatewayResult:
        started = self._clock()
        trace = _Trace()
        try:
            authorized = await self._authorize(call, trace)
        except _Refusal as refusal:
            await self._audit_failure(call, trace, "denied", refusal.code, refusal.rule_id, started)
            raise CallDenied(refusal.code) from None
        except StoreError:
            log.warning("gateway : stockage indisponible (étape %d)", call.step_seq)
            raise CallFailed("storage_unavailable") from None
        try:
            return await self._execute(call, trace, authorized, started)
        except CallFailed as failure:
            await self._audit_failure(
                call, trace, "error", failure.code, authorized.verdict.rule_id, started
            )
            raise

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
        declared = call.params.get("environment")
        if "environment" in call.params and declared != plan_environment:
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

    # --- Étapes 8 et 9 : exécuter et filtrer --------------------------------------------------

    async def _execute(
        self, call: GatewayCall, trace: _Trace, authorized: _Authorized, started: float
    ) -> GatewayResult:
        tool = authorized.tool
        adapter = self._adapters[tool.connector]
        try:
            async with asyncio.timeout(tool.timeout_s):
                raw = await adapter.execute(tool.tool, call.params, call.idempotency_key)
        except TimeoutError:
            raise CallFailed("timeout") from None
        except PermissionMissing:
            raise CallFailed("permission_missing") from None
        except ForeignResource:
            raise CallFailed("foreign_resource") from None
        except AdapterError:
            raise CallFailed("adapter_error") from None
        except Exception as exc:
            # Défaut de l'adaptateur : on ne journalise que le type, jamais le message.
            log.warning("gateway : défaut d'adaptateur (%s)", type(exc).__name__)
            raise CallFailed("adapter_defect") from None
        fields = frozenset(tool.redact)
        resources = self._resources(call, tool, raw.output)
        output = redact_value(dict(raw.output), fields)
        if not isinstance(output, dict) or json_size(output) > MAX_OUTPUT_BYTES:
            raise CallFailed("invalid_output")
        elapsed_ms = min(int((self._clock() - started) * 1000), MAX_AUDIT_DURATION_MS)
        audit = AuditEntry(
            actor_kind=ACTOR_KIND,
            project_id=call.project_id,
            plan_id=trace.plan_id,
            execution_id=call.execution_id,
            step_seq=call.step_seq,
            plan_hash=trace.plan_hash,
            actor=self._role,
            tool=tool.tool,
            tool_class=tool.tool_class,
            decision="allow",
            rule_id=authorized.verdict.rule_id,
            params_redacted=bounded_for_audit(call.params, fields),
            result_redacted=output,
            duration_ms=max(elapsed_ms, 0),
        )
        return GatewayResult(
            output=output, logs=filter_logs(raw.logs), resources=resources, audit=audit
        )

    @staticmethod
    def _resources(
        call: GatewayCall, tool: ToolDefinition, output: Mapping[str, JsonValue]
    ) -> tuple[NewResource, ...]:
        """Ressource créée, lue sur la sortie brute (le masquage ne doit pas altérer l'id)."""
        entry = tool.registry
        if entry is None:
            return ()
        found = output.get(entry.external_id, call.params.get(entry.external_id))
        external_id = _identifier(found)
        if external_id is None:
            raise CallFailed("invalid_output")
        url = output.get("web_url")
        safe_url = url if isinstance(url, str) and url.startswith(("https://", "http://")) else None
        return (NewResource(tool.connector, entry.resource_type, external_id, safe_url),)

    # --- Étape 10 : audit des refus et des échecs ---------------------------------------------

    async def _audit_failure(
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
        fields = frozenset(tool.redact) if tool is not None else frozenset()
        entry = AuditEntry(
            actor_kind=ACTOR_KIND,
            project_id=call.project_id,
            plan_id=trace.plan_id,
            execution_id=call.execution_id,
            step_seq=call.step_seq,
            plan_hash=trace.plan_hash,
            actor=self._role,
            tool=(tool.tool if tool is not None else mask_text(call.tool)[:MAX_TOOL_NAME_AUDIT]),
            tool_class=tool.tool_class if tool is not None else None,
            decision=decision,
            rule_id=rule_id,
            params_redacted=bounded_for_audit(call.params, fields) if tool is not None else None,
            result_redacted={"code": code},
            duration_ms=min(max(int((self._clock() - started) * 1000), 0), MAX_AUDIT_DURATION_MS),
        )
        try:
            await self._stores.audit.append(entry)
        except StoreError:
            log.warning("gateway : audit non écrit (%s)", code)
