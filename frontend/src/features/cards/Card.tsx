import {
  ArrowPathIcon,
  ArrowUturnLeftIcon,
  CheckCircleIcon,
  ClockIcon,
  ExclamationTriangleIcon,
  MinusCircleIcon,
} from "@heroicons/react/24/outline";
import type { ComponentType, SVGProps } from "react";
import type { PlanCardData, StepStatus } from "../../api/events";
import { Badge } from "@/components/ui/badge";
import { Card as UiCard, CardContent, CardDescription, CardHeader } from "@/components/ui/card";

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
    <Badge variant={status === "failed" ? "destructive" : "secondary"} className="shrink-0">
      <Icon aria-hidden="true" />
      {known?.label ?? String(status)}
    </Badge>
  );
}

function PlanCard({ card }: { card: PlanCardData }) {
  return (
    <UiCard>
      <CardHeader>
        <h3 className="text-base font-semibold">{card.title}</h3>
        <CardDescription className="whitespace-pre-wrap">{card.summary}</CardDescription>
      </CardHeader>
      <CardContent>
        <ol className="space-y-2">
          {card.steps.map((step) => (
            <li
              key={step.step}
              className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1 rounded-lg bg-muted px-3 py-2 text-sm"
            >
              <span className="min-w-0 break-words">
                <span className="mr-2 font-mono text-xs text-muted-foreground">{step.step}.</span>
                {step.title}
              </span>
              <StepStatusBadge status={step.status} />
            </li>
          ))}
        </ol>
      </CardContent>
    </UiCard>
  );
}

/** Carte générique : le rendu dépend de `kind`, avec repli pour les genres non pris en charge. */
export function Card({ card }: { card: PlanCardData }) {
  switch (card.kind) {
    case "plan":
      return <PlanCard card={card} />;
    default:
      return (
        <UiCard className="border border-dashed bg-muted text-sm text-muted-foreground">
          <CardContent>Carte non prise en charge.</CardContent>
        </UiCard>
      );
  }
}
