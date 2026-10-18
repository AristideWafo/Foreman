import { PlayCircleIcon } from "@heroicons/react/24/outline";
import type { ExecutionCardData } from "../../api/events";
import { CardHeading } from "@/components/CardHeading";
import { ExternalLink } from "@/components/ExternalLink";
import { Card, CardContent } from "@/components/ui/card";
import type { StepLogs } from "../events/timeline";
import { FactList, type Fact } from "./FactList";
import { ResourceList } from "./ResourceList";
import { StepList } from "./StepList";
import { executionStateLabel } from "./vocabulary";

function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
}

/** Budget, autonomie, ressources créées et résultat d'une exécution (partagés avec la carte plan). */
export function executionFacts(card: ExecutionCardData): Fact[] {
  const { budget, result } = card;
  const links = result?.links ?? [];
  return [
    {
      label: "Budget",
      value: `${budget.tool_calls_used} sur ${budget.tool_calls_max} appels d'outils · ${formatDuration(budget.elapsed_s)} sur ${budget.max_minutes} min`,
    },
    {
      label: "Ressources",
      value: card.resources.length > 0 ? <ResourceList resources={card.resources} linked /> : null,
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
  ];
}

/** Exécution sans plan connu dans la conversation (repli) : état, étapes avec leur journal, faits. Lecture seule. */
export function ExecutionCard({ card, logs }: { card: ExecutionCardData; logs: StepLogs }) {
  return (
    <Card role="group" aria-label="Exécution" className="ring-0">
      <CardHeading
        icon={<PlayCircleIcon aria-hidden="true" />}
        title="Exécution"
        badge={executionStateLabel(card.state)}
        badgeLabel="État de l'exécution"
        live
      />
      <CardContent className="flex flex-col gap-4">
        <StepList steps={card.steps} logs={logs} />
        <FactList
          facts={[
            {
              label: "Autonomie",
              value:
                typeof card.autonomy_level === "number" ? `Niveau ${card.autonomy_level}` : null,
            },
            ...executionFacts(card),
          ]}
        />
      </CardContent>
    </Card>
  );
}
