import { CheckIcon, ClipboardDocumentListIcon } from "@heroicons/react/24/outline";
import type { ExecutionCardData, PlanCardData } from "../../api/events";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CardHeading } from "@/components/CardHeading";
import { CollapsibleSection } from "@/components/CollapsibleSection";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import type { StepLogs } from "../events/timeline";
import { executionFacts } from "./ExecutionCard";
import { ResourceList } from "./ResourceList";
import { FactList } from "./FactList";
import { RETRYABLE_STATES, RetryPlan } from "./RetryPlan";
import { StepList } from "./StepList";
import { usePlanApproval } from "./usePlanApproval";
import { executionStateLabel, planStatusLabel, shortHash } from "./vocabulary";

/** Action « Valider le plan » : un clic. Recréée (`key`) à chaque carte réémise. */
function ApprovePlan({
  projectId,
  planId,
  planHash,
  adminRequired,
}: {
  projectId: string;
  planId: string;
  planHash: string;
  adminRequired: boolean;
}) {
  const { approve, pending, approved, awaitingAdmin, waitingForCard, errorMessage } =
    usePlanApproval(projectId, planId, planHash);
  if (approved) {
    return (
      <p role="status" className="flex items-center gap-2 text-sm">
        <CheckIcon aria-hidden="true" />
        {awaitingAdmin
          ? "Validé. En attente d'un administrateur."
          : "Plan validé. L'exécution démarre."}
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
        {pending
          ? "Validation en cours…"
          : adminRequired
            ? "Valider et transmettre à l'admin"
            : "Valider le plan"}
      </Button>
      {errorMessage ? (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

/**
 * Carte plan : ce que l'agent propose, et l'unique action « Valider le plan ». Une fois le plan validé,
 * l'exécution s'affiche dans cette même carte : mêmes étapes, statuts et journaux en direct.
 */
export function PlanCard({
  card,
  projectId,
  execution,
  logs = {},
  retryText,
}: {
  card: PlanCardData;
  projectId: string;
  execution?: ExecutionCardData;
  logs?: StepLogs;
  /** Message à renvoyer si cette exécution est bloquée (dernière exécution du projet seulement). */
  retryText?: string;
}) {
  const steps = execution?.steps ?? card.steps;
  const done = steps.filter((s) => s.status === "succeeded").length;
  const { plan_id: planId, plan_hash: planHash } = card;
  const canApprove = !execution && card.approvable === true && card.status === "proposed";
  const stack = Object.entries(card.stack ?? {});
  const skills = card.skills ?? [];
  const resources = card.expected_resources ?? [];

  return (
    <Card role="group" aria-label={`Plan : ${card.title}`} className="ring-0">
      <CardHeading
        icon={<ClipboardDocumentListIcon aria-hidden="true" />}
        title={`Plan : ${card.title}`}
        badge={execution ? executionStateLabel(execution.state) : planStatusLabel(card.status)}
        badgeLabel={execution ? "État de l'exécution" : "Statut du plan"}
        live={Boolean(execution)}
        description={card.summary}
      />
      <CardContent className="flex flex-col gap-4">
        <CollapsibleSection title={`Étapes : ${done} sur ${steps.length} terminées`}>
          <StepList steps={steps} logs={logs} />
        </CollapsibleSection>
        <div
          className="motion-safe:animate-in motion-safe:duration-300 motion-safe:fade-in-0 motion-safe:fill-mode-backwards"
          style={{ animationDelay: `${steps.length * 120 + 200}ms` }}
        >
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
                value: resources.length > 0 ? <ResourceList resources={resources} /> : null,
              },
              {
                label: "Empreinte",
                value: card.plan_hash ? (
                  <code className="font-mono text-xs" title={card.plan_hash}>
                    {shortHash(card.plan_hash)}
                  </code>
                ) : null,
              },
              ...(execution ? executionFacts(execution) : []),
            ]}
          />
        </div>
      </CardContent>
      {canApprove && planId && planHash ? (
        <CardFooter className="border-t-0 bg-transparent">
          <ApprovePlan
            key={`${planId}:${planHash}:${card.status}`}
            projectId={projectId}
            planId={planId}
            planHash={planHash}
            adminRequired={card.admin_approval_required === true}
          />
        </CardFooter>
      ) : null}
      {retryText && execution && RETRYABLE_STATES.includes(execution.state) ? (
        <RetryPlan projectId={projectId} text={retryText} />
      ) : null}
    </Card>
  );
}
