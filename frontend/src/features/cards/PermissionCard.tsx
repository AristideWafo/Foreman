import { KeyIcon } from "@heroicons/react/24/outline";
import type { PermissionCardData } from "../../api/events";
import { CardHeading } from "@/components/CardHeading";
import { LinkButton } from "@/components/LinkButton";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { RetryPlan } from "./RetryPlan";
import { toolLabel } from "./vocabulary";

/** Lecture du chat refusée faute de droit sur le jeton : nomme le droit, propose de relancer. */
export function PermissionCard({
  card,
  projectId,
  retryText,
}: {
  card: PermissionCardData;
  projectId: string;
  retryText?: string;
}) {
  return (
    <Card role="group" aria-label="Droit manquant" className="ring-0">
      <CardHeading
        icon={<KeyIcon aria-hidden="true" />}
        title="Droit manquant"
        description={`Foreman n'a pas pu faire ${toolLabel(card.tool).toLowerCase()} : le jeton GitLab « ${card.label} » n'a pas le droit requis (jeton expiré ou accès au groupe possible).`}
      />
      <CardContent className="flex flex-col gap-2 text-sm">
        <div className="flex flex-wrap gap-1">
          {card.scopes.map((scope) => (
            <Badge key={scope} variant="secondary">
              {scope}
            </Badge>
          ))}
        </div>
        {card.boundary ? (
          <p className="text-muted-foreground">Périmètre : {card.boundary}</p>
        ) : null}
        <p>
          Un administrateur d'organisation corrige le jeton puis clique « Vérifier » dans
          Administration &gt; Intégrations.
        </p>
        <div>
          <LinkButton to="/admin" variant="outline">
            Ouvrir l'administration
          </LinkButton>
        </div>
      </CardContent>
      {retryText ? (
        <RetryPlan
          projectId={projectId}
          text={retryText}
          label="Relancer"
          description="Une fois le droit corrigé, relancez la même demande."
          sentLabel="Demande relancée."
        />
      ) : null}
    </Card>
  );
}
