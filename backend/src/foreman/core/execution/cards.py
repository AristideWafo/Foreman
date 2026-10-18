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
from foreman.core.store import ExecutionRecord, ResourceRecord, Stores

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


def _resource_ref(resource: ResourceRecord) -> ResourceRef:
    return ResourceRef(
        provider=resource.provider[:50],
        resource_type=resource.resource_type[:50],
        name=resource.external_id[:200],
        url=_safe_url(resource.external_url),
    )


def _result(
    execution: ExecutionRecord, content: PlanContent, refs: list[ResourceRef]
) -> ExecutionResult | None:
    if execution.state == "succeeded":
        links = [
            Link(label=f"{r.resource_type} {r.name}"[:100], url=r.url)
            for r in refs
            if r.url is not None
        ][:MAX_LINKS]
        total = len(execution.steps)
        summary = f"{total} étapes réussies sur {total} en {content.environment}."
        return ExecutionResult(summary=summary, links=links)
    if execution.state == "blocked":
        unfinished = [s.seq for s in execution.steps if s.status != "succeeded"]
        where = f" à l'étape {min(unfinished)}" if unfinished else ""
        return ExecutionResult(
            summary=f"L'exécution est bloquée{where}. Rien d'autre n'a été lancé."
        )
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
    content = PlanContent.model_validate(plan.content)
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
    refs = [_resource_ref(r) for r in registry if r.execution_id == execution_id][:MAX_RESOURCES]
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
        result=_result(execution, content, refs),
    )
