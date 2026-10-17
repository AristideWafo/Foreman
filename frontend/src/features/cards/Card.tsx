import {
  CheckCircleIcon,
  ClockIcon,
  ExclamationTriangleIcon,
  MinusCircleIcon,
  ArrowPathIcon,
  ArrowUturnLeftIcon,
} from "@heroicons/react/24/outline";
import type { ComponentType, SVGProps } from "react";
import type { PlanCardData, StepStatus } from "../../api/events";

const STATUS: Record<StepStatus, { label: string; Icon: ComponentType<SVGProps<SVGSVGElement>> }> =
  {
    pending: { label: "En attente", Icon: ClockIcon },
    running: { label: "En cours", Icon: ArrowPathIcon },
    succeeded: { label: "Réussie", Icon: CheckCircleIcon },
    failed: { label: "Échouée", Icon: ExclamationTriangleIcon },
    compensated: { label: "Annulée (compensée)", Icon: ArrowUturnLeftIcon },
    skipped: { label: "Ignorée", Icon: MinusCircleIcon },
  };

function StepStatusBadge({ status }: { status: StepStatus }) {
  // Un statut hors contrat s'affiche tel quel, sans icône spécifique.
  const known = STATUS[status] as (typeof STATUS)[StepStatus] | undefined;
  const Icon = known?.Icon ?? ClockIcon;
  return (
    <span className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-slate-600">
      <Icon className="size-4" aria-hidden="true" />
      {known?.label ?? String(status)}
    </span>
  );
}

function PlanCard({ card }: { card: PlanCardData }) {
  return (
    <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="text-base font-semibold text-slate-900">{card.title}</h3>
      <p className="mt-1 whitespace-pre-wrap text-sm text-slate-600">{card.summary}</p>
      <ol className="mt-3 space-y-2">
        {card.steps.map((step) => (
          <li
            key={step.step}
            className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1 rounded-lg bg-slate-50 px-3 py-2 text-sm"
          >
            <span className="min-w-0 break-words text-slate-800">
              <span className="mr-2 font-mono text-xs text-slate-500">{step.step}.</span>
              {step.title}
            </span>
            <StepStatusBadge status={step.status} />
          </li>
        ))}
      </ol>
    </article>
  );
}

/** Carte générique : le rendu dépend de `kind`, avec repli pour les genres non pris en charge. */
export function Card({ card }: { card: PlanCardData }) {
  switch (card.kind) {
    case "plan":
      return <PlanCard card={card} />;
    default:
      return (
        <article className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4 text-sm text-slate-600">
          Carte non prise en charge.
        </article>
      );
  }
}
