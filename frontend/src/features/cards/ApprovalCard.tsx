import { CheckIcon, MinusCircleIcon, ShieldCheckIcon } from "@heroicons/react/24/outline";
import type { ApprovalCardData } from "../../api/events";
import { CardHeading } from "@/components/CardHeading";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { FactList } from "./FactList";
import { useAdminApproval } from "./useAdminApproval";
import { useMe } from "./useMe";
import { shortHash } from "./vocabulary";

/** « Approuver » (un clic) et « Refuser ». Recréé (`key`) à chaque carte réémise. */
function Decision({ card, projectId }: { card: ApprovalCardData; projectId: string }) {
  const { approve, reject, pending, sent, waitingForCard, errorMessage } = useAdminApproval(
    projectId,
    card.plan_id,
    card.plan_hash,
  );
  const disabled = pending || sent || waitingForCard;
  return (
    <div className="flex w-full flex-col items-start gap-2">
      <div className="flex flex-wrap gap-2">
        <Button type="button" onClick={approve} disabled={disabled} aria-busy={pending}>
          {pending ? "Envoi en cours…" : "Approuver"}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={reject}
          disabled={disabled}
          aria-busy={pending}
        >
          Refuser
        </Button>
      </div>
      {errorMessage ? (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

/** Demande d'approbation administrateur : le serveur décide, le rôle de `/api/me` ne sert qu'à montrer les boutons. */
export function ApprovalCard({ card, projectId }: { card: ApprovalCardData; projectId: string }) {
  const me = useMe();
  const canDecide =
    card.status === "pending" && me !== undefined && card.approver_roles.includes(me.role);

  let status = null;
  if (card.status === "approved" || card.status === "rejected") {
    const Icon = card.status === "approved" ? CheckIcon : MinusCircleIcon;
    const verb = card.status === "approved" ? "Approuvée" : "Refusée";
    status = (
      <p role="status" className="flex items-center gap-2 text-sm">
        <Icon aria-hidden="true" />
        {card.decided_by ? `${verb} par ${card.decided_by.name}` : verb}
      </p>
    );
  } else if (!canDecide) {
    status = (
      <p role="status" className="text-sm">
        En attente d'un administrateur
      </p>
    );
  }

  return (
    <Card role="group" aria-label="Approbation administrateur" className="ring-0">
      <CardHeading
        icon={<ShieldCheckIcon aria-hidden="true" />}
        title="Approbation administrateur"
        description="Ce plan vise la production : un administrateur doit l'approuver."
      />
      <CardContent>
        <FactList
          facts={[
            { label: "Environnement", value: card.environment },
            { label: "Demandé par", value: card.requested_by.name },
            { label: "Règle", value: card.rule_id },
            {
              label: "Empreinte",
              value: (
                <code className="font-mono text-xs" title={card.plan_hash}>
                  {shortHash(card.plan_hash)}
                </code>
              ),
            },
          ]}
        />
      </CardContent>
      {status || canDecide ? (
        <CardFooter className="border-t-0 bg-transparent">
          {canDecide ? (
            <Decision key={`${card.card_id}:${card.status}`} card={card} projectId={projectId} />
          ) : (
            status
          )}
        </CardFooter>
      ) : null}
    </Card>
  );
}
