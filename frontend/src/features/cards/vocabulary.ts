import {
  ArrowPathIcon,
  ArrowUturnLeftIcon,
  CheckCircleIcon,
  ClockIcon,
  ExclamationCircleIcon,
  MinusCircleIcon,
  PlayCircleIcon,
} from "@heroicons/react/24/outline";
import type { ComponentType, SVGProps } from "react";
import type { CardStep, ExecutionState, PlanStatus, StepStatus } from "../../api/events";

export type Icon = ComponentType<SVGProps<SVGSVGElement>>;
export type LineStatus = "running" | "error" | "pending" | undefined;

/** Libellé d'une valeur du contrat ; une valeur inconnue (évolution additive) s'affiche telle quelle. */
function label<K extends string>(labels: Record<K, string>, value: string | null | undefined) {
  if (value === null || value === undefined) return null;
  return (labels as Record<string, string | undefined>)[value] ?? value;
}

export const STEP_STATUS: Record<StepStatus, { label: string; Icon: Icon; line: LineStatus }> = {
  pending: { label: "En attente", Icon: ClockIcon, line: "pending" },
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
