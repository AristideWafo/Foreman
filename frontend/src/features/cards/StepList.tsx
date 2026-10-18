import type { CardStep } from "../../api/events";
import { CollapsibleSection } from "@/components/CollapsibleSection";
import { reveal } from "@/components/reveal";
import { Trace } from "@/components/ui/trace";
import type { StepLogs } from "../events/timeline";
import { reversibilityLabel, stepStatus, toolClassLabel } from "./vocabulary";

/** Détail d'une étape : outil, classe, réversibilité (champs facultatifs, `null` si absents). */
function stepMeta(step: CardStep): string {
  return [step.tool, toolClassLabel(step.tool_class), reversibilityLabel(step.reversibility)]
    .filter((part): part is string => typeof part === "string" && part !== "")
    .join(" · ");
}

/** Journal filtré d'une étape : défilement interne, focalisable au clavier. */
function LogBlock({ step, lines }: { step: number; lines: readonly string[] }) {
  return (
    <pre
      role="log"
      aria-label={`Journal de l'étape ${step}`}
      tabIndex={0}
      className="mt-1 max-h-40 overflow-auto rounded-md bg-muted p-2 font-mono text-xs wrap-break-word whitespace-pre-wrap text-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {lines.join("\n")}
    </pre>
  );
}

/**
 * Étapes d'un plan ou d'une exécution : une ligne repliable par étape (détail de l'outil, puis son journal
 * quand il arrive), avec son statut lu aux lecteurs d'écran.
 */
export function StepList({ steps, logs = {} }: { steps: readonly CardStep[]; logs?: StepLogs }) {
  return (
    <Trace>
      {steps.map((step, index) => {
        const status = stepStatus(String(step.status));
        const meta = stepMeta(step);
        const lines = logs[step.step] ?? [];
        const { className, style } = reveal(index, 120);
        return (
          <CollapsibleSection
            key={step.step}
            className={className}
            style={style}
            status={status.line === "pending" ? undefined : status.line}
            icon={<status.Icon />}
            title={
              <>
                <span className="font-mono">{step.step}.</span> {step.title}
                <span className="sr-only"> : {status.label}</span>
              </>
            }
          >
            {meta || lines.length > 0 ? (
              <>
                {meta ? <p className="font-mono text-xs">{meta}</p> : null}
                {lines.length > 0 ? <LogBlock step={step.step} lines={lines} /> : null}
              </>
            ) : null}
          </CollapsibleSection>
        );
      })}
    </Trace>
  );
}
