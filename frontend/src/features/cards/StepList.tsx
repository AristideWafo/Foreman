import type { CardStep } from "../../api/events";
import { Trace, TraceIcon, TraceLine, TraceTitle } from "@/components/ui/trace";
import { reversibilityLabel, stepStatus, toolClassLabel } from "./vocabulary";

/** Détail d'une étape : outil, classe, réversibilité (champs facultatifs, `null` si absents). */
function stepMeta(step: CardStep): string {
  return [step.tool, toolClassLabel(step.tool_class), reversibilityLabel(step.reversibility)]
    .filter((part): part is string => typeof part === "string" && part !== "")
    .join(" · ");
}

/** Étapes d'un plan ou d'une exécution : une ligne par étape, avec son statut (lu aux lecteurs d'écran). */
export function StepList({ steps }: { steps: readonly CardStep[] }) {
  return (
    <Trace>
      {steps.map((step, index) => {
        const status = stepStatus(String(step.status));
        const meta = stepMeta(step);
        return (
          <div
            key={step.step}
            className="flex flex-col gap-0.5 motion-safe:animate-in motion-safe:duration-200 motion-safe:fade-in-0 motion-safe:slide-in-from-left-1 motion-safe:fill-mode-backwards"
            style={{ animationDelay: `${index * 120}ms` }}
          >
            <TraceLine status={status.line}>
              <TraceIcon>
                <status.Icon />
              </TraceIcon>
              <TraceTitle>
                <span className="font-mono">{step.step}.</span> {step.title}
                <span className="sr-only"> : {status.label}</span>
              </TraceTitle>
            </TraceLine>
            {meta ? <p className="pl-7 font-mono text-xs text-muted-foreground">{meta}</p> : null}
          </div>
        );
      })}
    </Trace>
  );
}
