import {
  ArrowPathIcon,
  ArrowUturnLeftIcon,
  CheckCircleIcon,
  ClipboardDocumentListIcon,
  ClockIcon,
  ExclamationCircleIcon,
  MinusCircleIcon,
  PlayCircleIcon,
} from "@heroicons/react/24/outline";
import type { ComponentType, SVGProps } from "react";
import type { CardData, PlanCardData, StepStatus } from "../../api/events";
import { Card as UiCard, CardContent } from "@/components/ui/card";
import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@/components/ui/trace";

type Icon = ComponentType<SVGProps<SVGSVGElement>>;
type LineStatus = "running" | "error" | "pending" | undefined;

const STATUS: Record<StepStatus, { label: string; Icon: Icon; line: LineStatus }> = {
  pending: { label: "En attente", Icon: ClockIcon, line: "pending" },
  running: { label: "En cours", Icon: PlayCircleIcon, line: "running" },
  succeeded: { label: "Réussie", Icon: CheckCircleIcon, line: undefined },
  failed: { label: "Échouée", Icon: ExclamationCircleIcon, line: "error" },
  compensated: { label: "Annulée (compensée)", Icon: ArrowUturnLeftIcon, line: undefined },
  skipped: { label: "Ignorée", Icon: MinusCircleIcon, line: undefined },
};

function PlanCard({ card }: { card: PlanCardData }) {
  const done = card.steps.filter((s) => s.status === "succeeded").length;
  return (
    <TraceCollapsible defaultOpen>
      <TraceCollapsibleTrigger>
        <TraceLine>
          <TraceIcon>
            <ClipboardDocumentListIcon />
          </TraceIcon>
          <TraceTitle>Plan : {card.title}</TraceTitle>
          <TraceDescription>
            {done} sur {card.steps.length} terminées
          </TraceDescription>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        {card.summary ? <p className="mb-2 text-sm whitespace-pre-wrap">{card.summary}</p> : null}
        <Trace>
          {card.steps.map((step) => {
            // Un statut hors contrat s'affiche tel quel, sans icône spécifique.
            const known = STATUS[step.status] as (typeof STATUS)[StepStatus] | undefined;
            const StatusIcon = known?.Icon ?? ArrowPathIcon;
            return (
              <TraceLine key={step.step} status={known?.line}>
                <TraceIcon>
                  <StatusIcon />
                </TraceIcon>
                <TraceTitle>
                  <span className="font-mono">{step.step}.</span> {step.title}
                  <span className="sr-only"> : {known?.label ?? String(step.status)}</span>
                </TraceTitle>
              </TraceLine>
            );
          })}
        </Trace>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}

/** Carte générique : le rendu dépend de `kind`, avec repli pour les genres non pris en charge. */
export function Card({ card }: { card: CardData }) {
  switch (card.kind) {
    case "plan":
      return <PlanCard card={card} />;
    default:
      return (
        <UiCard className="border border-dashed text-sm">
          <CardContent>Carte non prise en charge.</CardContent>
        </UiCard>
      );
  }
}
