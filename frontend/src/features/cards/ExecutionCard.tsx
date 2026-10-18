import { PlayCircleIcon } from "@heroicons/react/24/outline";
import type { ExecutionCardData } from "../../api/events";
import { ExternalLink } from "@/components/ExternalLink";
import { Badge } from "@/components/ui/badge";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { StepLogs } from "../events/timeline";
import { FactList } from "./FactList";
import { StepList } from "./StepList";
import { executionStateLabel } from "./vocabulary";

/** Journal filtré d'une étape : défilement interne, focalisable au clavier. */
function StepLog({ step, lines }: { step: number; lines: readonly string[] }) {
  return (
    <div className="flex flex-col gap-1">
      <h4 className="text-xs text-muted-foreground">Journal de l'étape {step}</h4>
      <pre
        role="log"
        aria-label={`Journal de l'étape ${step}`}
        tabIndex={0}
        className="max-h-40 overflow-auto rounded-md bg-muted p-2 font-mono text-xs wrap-break-word whitespace-pre-wrap outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        {lines.join("\n")}
      </pre>
    </div>
  );
}

function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

/** Carte exécution : état, étapes dynamiques, journal, budget, ressources et résultat. Lecture seule. */
export function ExecutionCard({ card, logs }: { card: ExecutionCardData; logs: StepLogs }) {
  const state = executionStateLabel(card.state);
  const logged = Object.keys(logs)
    .map(Number)
    .filter((step) => (logs[step]?.length ?? 0) > 0)
    .sort((a, b) => a - b);
  const { budget, result } = card;
  const links = result?.links ?? [];

  return (
    <Card role="group" aria-label="Exécution">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <PlayCircleIcon aria-hidden="true" />
          Exécution
        </CardTitle>
        {state ? (
          <CardAction>
            <Badge variant="secondary" role="status">
              <span className="sr-only">État de l'exécution : </span>
              {state}
            </Badge>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <StepList steps={card.steps} />
        {logged.length > 0 ? (
          <section className="flex flex-col gap-2" aria-label="Journal">
            {logged.map((step) => (
              <StepLog key={step} step={step} lines={logs[step] ?? []} />
            ))}
          </section>
        ) : null}
        <FactList
          facts={[
            {
              label: "Budget",
              value: `${budget.tool_calls_used} sur ${budget.tool_calls_max} appels d'outils · ${formatDuration(budget.elapsed_s)} sur ${budget.max_minutes} min`,
            },
            {
              label: "Autonomie",
              value:
                typeof card.autonomy_level === "number" ? `Niveau ${card.autonomy_level}` : null,
            },
            {
              label: "Ressources",
              value:
                card.resources.length > 0 ? (
                  <ul className="flex flex-col">
                    {card.resources.map((r, index) => (
                      <li key={`${index}:${r.provider}/${r.resource_type}/${r.name}`}>
                        <ExternalLink href={r.url}>{r.name}</ExternalLink>
                        <span className="text-xs text-muted-foreground">
                          {" "}
                          · {r.provider} · {r.resource_type}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null,
            },
            {
              label: "Résultat",
              value: result ? (
                <div className="flex flex-col gap-1">
                  <p className="whitespace-pre-wrap">{result.summary}</p>
                  {links.length > 0 ? (
                    <ul className="flex flex-col">
                      {links.map((link) => (
                        <li key={`${link.label}|${link.url}`}>
                          <ExternalLink href={link.url}>{link.label}</ExternalLink>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : null,
            },
          ]}
        />
      </CardContent>
    </Card>
  );
}
