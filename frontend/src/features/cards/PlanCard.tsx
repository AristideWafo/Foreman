import { CheckIcon, ClipboardDocumentListIcon } from "@heroicons/react/24/outline";
import type { PlanCardData } from "../../api/events";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { FactList } from "./FactList";
import { StepList } from "./StepList";
import { usePlanApproval } from "./usePlanApproval";
import { planStatusLabel, shortHash } from "./vocabulary";

/** Action « Valider le plan » : un clic. Recréée (`key`) à chaque carte réémise. */
function ApprovePlan({
  projectId,
  planId,
  planHash,
}: {
  projectId: string;
  planId: string;
  planHash: string;
}) {
  const { approve, pending, approved, waitingForCard, errorMessage } = usePlanApproval(
    projectId,
    planId,
    planHash,
  );
  if (approved) {
    return (
      <p role="status" className="flex items-center gap-2 text-sm">
        <CheckIcon aria-hidden="true" />
        Plan validé. L'exécution démarre.
      </p>
    );
  }
  return (
    <div className="flex w-full flex-col items-start gap-2">
      <Button
        type="button"
        onClick={approve}
        disabled={pending || waitingForCard}
        aria-busy={pending}
      >
        {pending ? "Validation en cours…" : "Valider le plan"}
      </Button>
      {errorMessage ? (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

/** Carte plan : ce que l'agent propose, et l'unique action « Valider le plan ». */
export function PlanCard({ card, projectId }: { card: PlanCardData; projectId: string }) {
  const done = card.steps.filter((s) => s.status === "succeeded").length;
  const { plan_id: planId, plan_hash: planHash } = card;
  const canApprove = card.approvable === true && card.status === "proposed";
  const stack = Object.entries(card.stack ?? {});
  const skills = card.skills ?? [];
  const resources = card.expected_resources ?? [];
  const status = planStatusLabel(card.status);

  return (
    <Card role="group" aria-label={`Plan : ${card.title}`}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ClipboardDocumentListIcon aria-hidden="true" />
          Plan : {card.title}
        </CardTitle>
        {status ? (
          <CardAction>
            <Badge variant="secondary">
              <span className="sr-only">Statut du plan : </span>
              {status}
            </Badge>
          </CardAction>
        ) : null}
        {card.summary ? (
          <CardDescription className="whitespace-pre-wrap">{card.summary}</CardDescription>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <section className="flex flex-col gap-2" aria-label="Étapes du plan">
          <h3 className="text-xs text-muted-foreground">
            Étapes : {done} sur {card.steps.length} terminées
          </h3>
          <StepList steps={card.steps} />
        </section>
        <FactList
          facts={[
            { label: "Environnement", value: card.environment },
            {
              label: "Autonomie",
              value:
                typeof card.autonomy_level === "number" ? `Niveau ${card.autonomy_level}` : null,
            },
            {
              label: "Stack",
              value:
                stack.length > 0
                  ? stack.map(([key, value]) => `${key} : ${value}`).join(", ")
                  : null,
            },
            {
              label: "Skills",
              value:
                skills.length > 0
                  ? skills.map((s) => `${s.name} (v${s.version})`).join(", ")
                  : null,
            },
            {
              label: "Ressources attendues",
              value:
                resources.length > 0 ? (
                  <ul className="flex flex-col">
                    {resources.map((r) => (
                      <li key={`${r.provider}/${r.resource_type}/${r.name}`}>
                        {r.name}
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
              label: "Empreinte",
              value: card.plan_hash ? (
                <code className="font-mono text-xs" title={card.plan_hash}>
                  {shortHash(card.plan_hash)}
                </code>
              ) : null,
            },
          ]}
        />
      </CardContent>
      {canApprove && planId && planHash ? (
        <CardFooter>
          <ApprovePlan
            key={`${planId}:${planHash}:${card.status}`}
            projectId={projectId}
            planId={planId}
            planHash={planHash}
          />
        </CardFooter>
      ) : null}
    </Card>
  );
}
