import type { CardData } from "../../api/events";
import { Card as UiCard, CardContent } from "@/components/ui/card";
import type { StepLogs } from "../events/timeline";
import { ExecutionCard } from "./ExecutionCard";
import { PlanCard } from "./PlanCard";

const NO_LOGS: StepLogs = {};

/** Carte générique : le rendu dépend de `kind`, avec repli pour les genres non pris en charge. */
export function Card({
  card,
  projectId,
  logs = NO_LOGS,
}: {
  card: CardData;
  projectId: string;
  logs?: StepLogs;
}) {
  switch (card.kind) {
    case "plan":
      return <PlanCard card={card} projectId={projectId} />;
    case "execution":
      return <ExecutionCard card={card} logs={logs} />;
    default:
      return (
        <UiCard className="border border-dashed text-sm">
          <CardContent>Carte non prise en charge.</CardContent>
        </UiCard>
      );
  }
}
