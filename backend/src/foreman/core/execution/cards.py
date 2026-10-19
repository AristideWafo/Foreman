"""Carte d'exécution : toujours reconstruite depuis l'état PERSISTÉ (source unique de vérité).

Le moteur l'émet à chaque changement ; la route `GET` de l'exécution en dérive sa vue. Les
identifiants de cartes sont déterministes (plan et exécution) : la carte plan peut être réémise et
l'exécution reprise après un redémarrage sans état partagé.
"""

from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from foreman.core.catalog import Catalog
from foreman.core.events import (
    Budget,
    CardStep,
    ExecutionCardData,
    ExecutionResult,
    Link,
    ResourceRef,
    StepStatus,
    Url,
)
from foreman.core.planning import PlanContent, plan_card_id
from foreman.core.store import ExecutionRecord, ResourceRecord, StoreError, Stores

MAX_LINKS = 10
MAX_RESOURCES = 50
_URL: TypeAdapter[str] = TypeAdapter(Url)


def execution_card_id(execution_id: UUID) -> str:
    return execution_id.hex


def step_status(execution: ExecutionRecord, status: str) -> StepStatus:
    """Une étape restée `running` dans une exécution bloquée est celle qui a échoué."""
    if status == "running" and execution.state == "blocked":
        return "failed"
    return status  # type: ignore[return-value]  # valeurs de la base, bornées par un CHECK


def _safe_url(url: str | None) -> str | None:
    if url is None:
        return None
    try:
        return _URL.validate_python(url)
    except ValidationError:
        return None


def _resource_ref(resource: ResourceRecord, execution_id: UUID) -> ResourceRef:
    return ResourceRef(
        provider=resource.provider[:50],
        resource_type=resource.resource_type[:50],
        name=resource.external_id[:200],
        url=_safe_url(resource.external_url),
        reused=True if resource.execution_id != execution_id else None,
    )


def _step_resources(
    catalog: Catalog, execution: ExecutionRecord, registry: list[ResourceRecord]
) -> list[ResourceRecord]:
    """Ressources de l'exécution, lues depuis les RÉSULTATS des étapes réussies (une étape rejouée
    ou réutilisée n'a plus de ligne à son nom au registre : la ressource appartient à l'exécution
    qui l'a créée)."""
    known = {(r.provider, r.resource_type, r.external_id): r for r in registry}
    found: list[ResourceRecord] = []
    for step in execution.steps:
        tool = catalog.tools.get(step.tool)
        if step.status != "succeeded" or tool is None or tool.registry is None or not step.result:
            continue
        if tool.effective_scope(step.params).kind != "create" or step.params.get("mode") == "check":
            continue
        value = tool.registry.identify(step.params, step.result)
        record = known.get((tool.connector, tool.registry.resource_type, str(value)))
        if record is not None:
            found.append(record)
    return found


_CAUSES = {
    "scope_violation": (
        "Cette ressource appartient à un autre projet ou sort du périmètre autorisé. "
        "Changez le nom du projet ou contactez un administrateur."
    ),
    "foreign_resource": (
        "Cette ressource appartient à un autre projet ou sort du périmètre autorisé. "
        "Changez le nom du projet ou contactez un administrateur."
    ),
    "adapter_error": (
        "Le fournisseur a refusé l'appel (état externe perdu ou indisponible). Relancez le plan."
    ),
}
_GENERIC_CAUSE = "Rien d'autre n'a été lancé."


async def _blocked_summary(stores: Stores, execution: ExecutionRecord) -> str:
    """Pourquoi l'exécution est bloquée, depuis le dernier refus ou échec audité par la gateway.
    Jamais d'identifiant ni de détail interne : seul le CODE (fermé) choisit le texte."""
    unfinished = [s.seq for s in execution.steps if s.status != "succeeded"]
    if not unfinished:
        return f"L'exécution est bloquée. {_GENERIC_CAUSE}"
    seq = min(unfinished)
    prefix = f"L'exécution est bloquée à l'étape {seq}. "
    try:
        entries = await stores.audit.list_for_project(
            execution.project_id,
            limit=500,
            execution_id=execution.id,
            step_seq=seq,
            newest_first=True,
        )
    except StoreError:
        return prefix + _GENERIC_CAUSE
    codes = [
        (e.result_redacted or {}).get("code") for e in entries if e.decision in ("denied", "error")
    ]
    return prefix + (_CAUSES.get(str(codes[0]), _GENERIC_CAUSE) if codes else _GENERIC_CAUSE)


def _result(
    execution: ExecutionRecord,
    content: PlanContent,
    refs: list[ResourceRef],
    blocked_summary: str | None,
) -> ExecutionResult | None:
    if execution.state == "succeeded":
        links = [
            Link(label=f"{r.resource_type} {r.name}"[:100], url=r.url)
            for r in refs
            if r.url is not None
        ][:MAX_LINKS]
        total = len(execution.steps)
        summary = f"{total} étapes réussies sur {total} en {content.environment}."
        if refs and all(r.reused for r in refs):
            summary += f" {len(refs)} ressources déjà présentes, aucune créée."
        return ExecutionResult(summary=summary, links=links)
    if blocked_summary is not None:
        return ExecutionResult(summary=blocked_summary)
    return None


async def execution_card(
    stores: Stores, catalog: Catalog, project_id: UUID, execution_id: UUID, elapsed_s: int = 0
) -> ExecutionCardData | None:
    """Vide si l'exécution ou son plan n'existent pas pour ce projet. Lève `StoreError`."""
    execution = await stores.executions.get(project_id, execution_id)
    if execution is None:
        return None
    plan = await stores.plans.get(project_id, execution.plan_id)
    if plan is None:
        return None
    try:
        content = PlanContent.model_validate(plan.content)
    except ValidationError:
        return None  # plan d'un ancien schéma (/1) : illisible, jamais une 500
    by_seq = {s.seq: s for s in content.steps}
    steps = [
        CardStep(
            step=s.seq,
            title=by_seq[s.seq].title,
            status=step_status(execution, s.status),
            tool=s.tool,
            tool_class=by_seq[s.seq].tool_class,
            reversibility=by_seq[s.seq].reversibility,
        )
        for s in execution.steps
        if s.seq in by_seq
    ]
    registry = await stores.registry.list_for_project(project_id)
    owned = _step_resources(catalog, execution, registry)
    refs = [_resource_ref(r, execution_id) for r in owned][:MAX_RESOURCES]
    budget = catalog.policy.budgets.per_execution
    started = sum(1 for s in execution.steps if s.status != "pending")
    return ExecutionCardData(
        card_id=execution_card_id(execution_id),
        kind="execution",
        execution_id=execution_id,
        plan_card_id=plan_card_id(execution.plan_id),
        state=execution.state,
        autonomy_level=execution.autonomy_level,
        steps=steps,
        budget=Budget(
            tool_calls_used=started,
            tool_calls_max=budget.max_tool_calls,
            elapsed_s=max(elapsed_s, 0),
            max_minutes=budget.max_minutes,
        ),
        resources=refs,
        result=_result(
            execution,
            content,
            refs,
            await _blocked_summary(stores, execution) if execution.state == "blocked" else None,
        ),
    )
