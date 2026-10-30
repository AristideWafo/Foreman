import {
  ArrowPathIcon,
  ArrowUturnLeftIcon,
  CheckCircleIcon,
  EllipsisHorizontalCircleIcon,
  ExclamationCircleIcon,
  MinusCircleIcon,
  PlayCircleIcon,
} from "@heroicons/react/24/outline";
import type { ComponentType, SVGProps } from "react";
import type {
  CardStep,
  ExecutionState,
  PlanChange,
  PlanCardData,
  PlanStatus,
  StepStatus,
} from "../../api/events";

export type Icon = ComponentType<SVGProps<SVGSVGElement>>;
export type LineStatus = "running" | "error" | "pending" | undefined;

/** Libellé d'une valeur du contrat ; une valeur inconnue (évolution additive) s'affiche telle quelle. */
function label<K extends string>(labels: Record<K, string>, value: string | null | undefined) {
  if (value === null || value === undefined) return null;
  return (labels as Record<string, string | undefined>)[value] ?? value;
}

export const STEP_STATUS: Record<StepStatus, { label: string; Icon: Icon; line: LineStatus }> = {
  pending: { label: "En attente", Icon: EllipsisHorizontalCircleIcon, line: "pending" },
  running: { label: "En cours", Icon: PlayCircleIcon, line: "running" },
  succeeded: { label: "Réussie", Icon: CheckCircleIcon, line: undefined },
  failed: { label: "Échouée", Icon: ExclamationCircleIcon, line: "error" },
  compensated: { label: "Annulée (compensée)", Icon: ArrowUturnLeftIcon, line: undefined },
  skipped: { label: "Ignorée", Icon: MinusCircleIcon, line: undefined },
};

/** Statut d'étape avec repli pour une valeur hors contrat. */
export function stepStatus(status: string) {
  const known = (STEP_STATUS as Record<string, (typeof STEP_STATUS)[StepStatus] | undefined>)[
    status
  ];
  return known ?? { label: status, Icon: ArrowPathIcon, line: undefined };
}

const PLAN_STATUS: Record<PlanStatus, string> = {
  proposed: "Proposé",
  dev_approved: "Validé",
  admin_approved: "Validé par un administrateur",
  invalidated: "Invalidé",
  expired: "Expiré",
  executed: "Exécuté",
};
export const planStatusLabel = (value: string | null | undefined) => label(PLAN_STATUS, value);

const EXECUTION_STATE: Record<ExecutionState, string> = {
  running: "En cours",
  awaiting_permission: "En attente d'autorisation",
  awaiting_remediation: "En attente de correction",
  succeeded: "Terminée",
  partial: "Terminée en partie",
  failed_compensated: "Échec, annulée",
  blocked: "Bloquée",
  degraded: "Dégradée",
};
export const executionStateLabel = (value: string | null | undefined) =>
  label(EXECUTION_STATE, value);

const TOOL_CLASS: Record<NonNullable<CardStep["tool_class"]>, string> = {
  read: "Lecture",
  write_registry: "Écriture (registre)",
  write_foreign: "Écriture (externe)",
  destructive: "Destructif",
  control: "Contrôle",
};
export const toolClassLabel = (value: string | null | undefined) => label(TOOL_CLASS, value);

const REVERSIBILITY: Record<NonNullable<CardStep["reversibility"]>, string> = {
  reversible: "Réversible",
  compensable: "Compensable",
  irreversible: "Irréversible",
  not_applicable: "Sans objet",
};
export const reversibilityLabel = (value: string | null | undefined) => label(REVERSIBILITY, value);

/** `sha256:` + 12 premiers caractères + `…` (empreinte lisible ; la valeur complète va dans une infobulle). */
export function shortHash(hash: string): string {
  const [prefix, hex] = hash.includes(":") ? hash.split(":", 2) : ["", hash];
  const head = (hex ?? "").slice(0, 12);
  return `${prefix ? `${prefix}:` : ""}${head}…`;
}

const INVALIDATION_REASON: Record<NonNullable<PlanCardData["invalidation"]>["reason"], string> = {
  catalog_changed: "Le catalogue a changé",
  project_changed: "Le projet a changé depuis ce plan",
  admin_rejected: "Refusé par un administrateur",
  expired: "Plan expiré",
};
export const invalidationReasonLabel = (value: string | null | undefined) =>
  label(INVALIDATION_REASON, value);

const CHANGE_KIND: Record<PlanChange["kind"], string> = {
  policy: "Règle",
  referential: "Référentiel",
  skill: "Skill",
  tool: "Outil",
  registry: "Registre",
};
export const changeKindLabel = (value: string | null | undefined) => label(CHANGE_KIND, value);

const TOOL_LABELS: Record<string, string> = {
  propose_plan: "Plan proposé",
  "gitlab.list_groups": "Lecture des groupes",
  "gitlab.list_projects": "Lecture des projets",
  "gitlab.get_project": "Lecture d'un projet",
  "gitlab.list_branches": "Lecture des branches",
  "gitlab.list_pipelines": "Lecture des pipelines",
  "gitlab.list_issues": "Lecture des tickets",
  "gitlab.list_merge_requests": "Lecture des demandes de fusion",
  "gitlab.read_file": "Lecture d'un fichier",
};

/** Un outil `gitlab.*` hors dictionnaire reste une lecture, sans nom technique affiché. */
export function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? (tool.startsWith("gitlab.") ? "Lecture" : tool);
}
