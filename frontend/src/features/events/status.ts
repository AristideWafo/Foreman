import type { ExecutionCardData, PlanCardData, ResourceRef, StepStatus } from "../../api/events";
import type { TimelineItem } from "./timeline";

/** Six états d'une ressource : « targeted » = prévue par le plan, pas encore faite. */
export type ResourceStatus = "targeted" | "running" | "created" | "reused" | "failed" | "cancelled";

export const RESOURCE_STATUSES: readonly ResourceStatus[] = [
  "targeted",
  "running",
  "created",
  "reused",
  "failed",
  "cancelled",
];

export interface ResourceView {
  provider: string;
  resource_type: string;
  name: string;
  url?: string | null;
  status: ResourceStatus;
}

export interface ProjectStatus {
  plan: PlanCardData | null;
  resources: ResourceView[];
  summary: {
    environment: string | null;
    title: string | null;
    planStatus: string | null;
    executionState: string | null;
    currentStep: string | null;
    counts: Record<ResourceStatus, number>;
    lastAction: string | null;
  } | null;
}

/** Statut d'une ressource selon l'état de son étape ; `done` = statut si l'étape a réussi. */
function fromStep(status: StepStatus, done: ResourceStatus): ResourceStatus {
  switch (status) {
    case "running":
      return "running";
    case "succeeded":
      return done;
    case "failed":
      return "failed";
    case "compensated":
      return "cancelled";
    default:
      return "targeted";
  }
}

/** Sans étape connue (ancien plan) : état global de l'exécution. */
function fromExecution(state: ExecutionCardData["state"], done: ResourceStatus): ResourceStatus {
  switch (state) {
    case "running":
      return "running";
    case "succeeded":
    case "partial":
    case "degraded":
      return done;
    case "failed_compensated":
      return "cancelled";
    case "blocked":
      return "failed";
    default:
      return "targeted";
  }
}

const doneOf = (ref: ResourceRef | undefined): ResourceStatus =>
  ref ? (ref.reused === true ? "reused" : "created") : "targeted";

function statusOf(
  execution: ExecutionCardData,
  step: number | null | undefined,
  ref: ResourceRef | undefined,
): ResourceStatus {
  const s = step == null ? undefined : execution.steps.find((x) => x.step === step);
  return s
    ? fromStep(s.status, ref?.reused === true ? "reused" : "created")
    : fromExecution(execution.state, doneOf(ref));
}

function lastLine(logs: Readonly<Record<number, readonly string[]>> | undefined): string | null {
  const steps = Object.keys(logs ?? {})
    .map(Number)
    .sort((a, b) => a - b);
  for (const step of steps.reverse()) {
    const lines = logs?.[step];
    if (lines?.length) return lines[lines.length - 1] ?? null;
  }
  return null;
}

/**
 * Dernier plan du projet et son exécution, dérivés des cartes déjà reçues (aucune requête) :
 * ressources ciblées par le plan avec leur statut, puis ressources de l'exécution sans équivalent.
 */
export function projectStatus(items: readonly TimelineItem[]): ProjectStatus {
  const last = [...items]
    .reverse()
    .find((i) => i.kind === "card" && (i.card.kind === "plan" || i.card.kind === "execution"));
  if (last?.kind !== "card") return { plan: null, resources: [], summary: null };
  const plan = last.card.kind === "plan" ? last.card : null;
  const executionItem =
    last.card.kind === "execution" ? { card: last.card, logs: last.logs } : last.execution;
  const execution = executionItem?.card;

  const refs = [...(execution?.resources ?? [])];
  // Une ressource ciblée prend la `ResourceRef` de la même étape, fournisseur et type (sinon du même nom).
  const take = (r: {
    provider: string;
    resource_type: string;
    name: string;
    step?: number | null;
  }) => {
    const same = (x: ResourceRef) =>
      x.provider === r.provider && x.resource_type === r.resource_type;
    const at = refs.findIndex(
      (x) => same(x) && (r.step == null ? x.name === r.name : x.step === r.step),
    );
    return at === -1 ? undefined : refs.splice(at, 1)[0];
  };

  const resources: ResourceView[] = [];
  for (const r of plan?.expected_resources ?? []) {
    const ref = take(r);
    resources.push({
      provider: r.provider,
      resource_type: r.resource_type,
      name: r.name, // nom choisi dans le plan : plus lisible que l'identifiant du fournisseur
      url: ref?.url,
      status: execution ? statusOf(execution, r.step, ref) : "targeted",
    });
  }
  for (const ref of refs) {
    resources.push({
      provider: ref.provider,
      resource_type: ref.resource_type,
      name: ref.name,
      url: ref.url,
      status: execution ? statusOf(execution, ref.step, ref) : doneOf(ref),
    });
  }

  const counts = Object.fromEntries(RESOURCE_STATUSES.map((s) => [s, 0])) as Record<
    ResourceStatus,
    number
  >;
  for (const r of resources) counts[r.status]++;
  return {
    plan,
    resources,
    summary: {
      environment: plan?.environment ?? null,
      title: plan?.title ?? null,
      planStatus: plan?.status ?? null,
      executionState: execution?.state ?? null,
      currentStep: execution?.steps.find((s) => s.status === "running")?.title ?? null,
      counts,
      lastAction: lastLine(executionItem?.logs),
    },
  };
}
