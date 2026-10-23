import { ArrowPathIcon, CheckCircleIcon, ExclamationCircleIcon } from "@heroicons/react/24/outline";
import { useEffect, useState } from "react";
import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from "@/components/ui/trace";

type TraceStatus = "running" | "done" | "error";

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
function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? (tool.startsWith("gitlab.") ? "Lecture" : tool);
}

const STEP_DELAY_MS = 150;
/** Même avec des données simulées, la réflexion reste « en cours » ce temps-là avant de se terminer. */
const MIN_RUNNING_MS = 1500;

function StatusIcon({ status }: { status: TraceStatus }) {
  if (status === "running") return <ArrowPathIcon className="motion-safe:animate-spin" />;
  if (status === "error") return <ExclamationCircleIcon />;
  return <CheckCircleIcon />;
}

function title(status: TraceStatus, steps: number): string {
  if (status === "running") return "Réflexion en cours";
  if (status === "error") return "Le tour a échoué";
  return `Réflexion terminée en ${steps} ${steps > 1 ? "étapes" : "étape"}`;
}

/** Activité d'un tour : ouverte pendant la réflexion, repliée une fois terminée ; les étapes apparaissent une à une. */
export function TurnTrace({
  status: actual,
  tools,
  failed = [],
}: {
  status: TraceStatus;
  tools: string[];
  failed?: string[];
}) {
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(true), MIN_RUNNING_MS);
    return () => clearTimeout(timer);
  }, []);
  const status: TraceStatus = actual === "done" && !settled ? "running" : actual;
  const [open, setOpen] = useState(status === "running");
  const [seen, setSeen] = useState(status);
  if (seen !== status) {
    // Replie la trace dès que la réflexion se termine (ajustement d'état pendant le rendu).
    setSeen(status);
    if (status !== "running") setOpen(false);
  }

  const analysis: TraceStatus =
    status === "running" && tools.length === 0 ? "running" : status === "error" ? "error" : "done";
  const steps = [
    { key: "analysis", label: "Analyse de la demande", status: analysis },
    ...tools.map((tool) => ({
      key: tool,
      label: failed.includes(tool) ? `${toolLabel(tool)} : échec` : toolLabel(tool),
      status: (failed.includes(tool)
        ? "error"
        : status === "running"
          ? "running"
          : "done") as TraceStatus,
    })),
  ];

  return (
    <TraceCollapsible open={open} onOpenChange={setOpen}>
      <TraceCollapsibleTrigger>
        <TraceLine status={status === "done" ? undefined : status}>
          <TraceIcon>
            <StatusIcon status={status} />
          </TraceIcon>
          <TraceTitle>{title(status, steps.length)}</TraceTitle>
        </TraceLine>
      </TraceCollapsibleTrigger>
      <TraceCollapsibleContent>
        <Trace>
          {steps.map((step, index) => (
            <TraceLine
              key={step.key}
              status={step.status === "done" ? undefined : step.status}
              className="motion-safe:animate-in motion-safe:duration-200 motion-safe:fade-in-0 motion-safe:slide-in-from-left-1 motion-safe:fill-mode-backwards"
              style={{ animationDelay: `${index * STEP_DELAY_MS}ms` }}
            >
              <TraceIcon>
                <StatusIcon status={step.status} />
              </TraceIcon>
              <TraceTitle>{step.label}</TraceTitle>
            </TraceLine>
          ))}
        </Trace>
      </TraceCollapsibleContent>
    </TraceCollapsible>
  );
}
