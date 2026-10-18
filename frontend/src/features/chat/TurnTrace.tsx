import { SparklesIcon, WrenchIcon } from "@heroicons/react/24/outline";
import { Trace, TraceIcon, TraceLine, TraceTitle } from "@/components/ui/trace";

type TraceStatus = "running" | "done" | "error";

const TOOL_LABELS: Record<string, string> = { propose_plan: "Plan proposé" };

const THINKING_LABEL: Record<TraceStatus, string> = {
  running: "Réflexion en cours",
  done: "Réflexion terminée",
  error: "Le tour a échoué",
};

/** Activité d'un tour de l'agent : réflexion, puis outils utilisés. */
export function TurnTrace({ status, tools }: { status: TraceStatus; tools: string[] }) {
  return (
    <Trace>
      <TraceLine status={status === "done" ? undefined : status}>
        <TraceIcon>
          <SparklesIcon />
        </TraceIcon>
        <TraceTitle>{THINKING_LABEL[status]}</TraceTitle>
      </TraceLine>
      {tools.map((tool) => (
        <TraceLine key={tool}>
          <TraceIcon>
            <WrenchIcon />
          </TraceIcon>
          <TraceTitle>{TOOL_LABELS[tool] ?? tool}</TraceTitle>
        </TraceLine>
      ))}
    </Trace>
  );
}
