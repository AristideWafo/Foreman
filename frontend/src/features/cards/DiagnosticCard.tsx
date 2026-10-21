import { useState } from "react";
import { ExclamationTriangleIcon } from "@heroicons/react/24/outline";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { DiagnosticCardData } from "../../api/events";
import { describeError, getRawLog, postMessage } from "../../api/client";
import { CardHeading } from "@/components/CardHeading";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter } from "@/components/ui/card";
import { LogBlock } from "./StepList";
import { useMe } from "./useMe";

/** Log brut : demandé au clic, le serveur ne le rend qu'aux administrateurs de l'équipe. */
function RawLog({ card, projectId }: { card: DiagnosticCardData; projectId: string }) {
  const [open, setOpen] = useState(false);
  const raw = useQuery({
    queryKey: ["raw-log", projectId, card.execution_id, card.step],
    queryFn: () => getRawLog(projectId, card.execution_id, card.step),
    enabled: open,
    retry: false,
  });
  return (
    <div className="flex w-full flex-col items-start gap-2">
      {open ? null : (
        <Button type="button" variant="outline" onClick={() => setOpen(true)}>
          Voir le log brut
        </Button>
      )}
      {raw.data ? (
        <LogBlock
          step={card.step}
          lines={raw.data.lines}
          label={`Log brut de l'étape ${card.step}`}
        />
      ) : null}
      {raw.isError ? (
        <Alert variant="destructive">
          <AlertDescription>Log brut indisponible pour votre rôle ou expiré.</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

/** Suite donnée par l'humain : un message envoyé au chat, le modèle reprend à partir de là. */
function NextStep({ card, projectId }: { card: DiagnosticCardData; projectId: string }) {
  const send = useMutation({ mutationFn: (text: string) => postMessage(projectId, text) });
  if (send.isSuccess) {
    return (
      <p role="status" className="text-sm">
        Réponse envoyée.
      </p>
    );
  }
  return (
    <div className="flex w-full flex-col items-start gap-2">
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          onClick={() => send.mutate(`Réessaie l'étape ${card.step} (${card.tool}).`)}
          disabled={send.isPending}
          aria-busy={send.isPending}
        >
          Réessayer
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => send.mutate("Annule : n'exécute pas la suite.")}
          disabled={send.isPending}
          aria-busy={send.isPending}
        >
          Annuler
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        Ou précisez la cause dans la zone de message ci-dessous.
      </p>
      {send.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{describeError(send.error)}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

/** Échec sans code connu : le modèle ne devine pas, l'humain décide (extrait masqué, log brut réservé aux admins). */
export function DiagnosticCard({
  card,
  projectId,
}: {
  card: DiagnosticCardData;
  projectId: string;
}) {
  const me = useMe();
  const canSeeRaw = card.raw_log_available && me !== undefined && me.role !== "developer";
  return (
    <Card role="group" aria-label="Diagnostic requis" className="ring-0">
      <CardHeading
        icon={<ExclamationTriangleIcon aria-hidden="true" />}
        title="Diagnostic requis"
        description={`L'étape ${card.step} (${card.tool}) a échoué sans cause connue. Dites-moi comment continuer.`}
      />
      <CardContent className="flex flex-col gap-2">
        {card.extract.length > 0 ? (
          <LogBlock
            step={card.step}
            lines={card.extract}
            label={`Extrait masqué de l'étape ${card.step}`}
          />
        ) : null}
        {canSeeRaw ? <RawLog card={card} projectId={projectId} /> : null}
      </CardContent>
      <CardFooter className="border-t-0 bg-transparent">
        <NextStep card={card} projectId={projectId} />
      </CardFooter>
    </Card>
  );
}
