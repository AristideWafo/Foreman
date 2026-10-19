import { ArrowPathIcon } from "@heroicons/react/24/outline";
import { useMutation } from "@tanstack/react-query";
import { describeError, postMessage } from "../../api/client";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CardFooter } from "@/components/ui/card";

/** États d'exécution qui laissent l'utilisateur sans issue : une relance est proposée. */
export const RETRYABLE_STATES: readonly string[] = ["blocked", "failed_compensated"];

/** Pied de carte « Relancer le plan » : renvoie le message d'origine, le nouveau plan arrive par le flux. */
export function RetryPlan({
  projectId,
  text,
  description = "L'exécution est bloquée. Vous pouvez relancer le plan : les ressources déjà créées sont réutilisées.",
  label = "Relancer le plan",
}: {
  projectId: string;
  text: string;
  description?: string;
  label?: string;
}) {
  const retry = useMutation({ mutationFn: () => postMessage(projectId, text) });
  return (
    <CardFooter className="flex-col items-start gap-2 border-t-0 bg-transparent">
      <p className="text-sm text-muted-foreground">{description}</p>
      {retry.isSuccess ? (
        <p role="status" className="text-sm">
          Demande envoyée. Un nouveau plan arrive.
        </p>
      ) : (
        <Button
          type="button"
          variant="outline"
          onClick={() => retry.mutate()}
          disabled={retry.isPending}
          aria-busy={retry.isPending}
        >
          <ArrowPathIcon data-icon="inline-start" />
          {retry.isPending ? "Relance en cours…" : label}
        </Button>
      )}
      {retry.isError ? (
        <Alert variant="destructive">
          <AlertDescription>{describeError(retry.error)}</AlertDescription>
        </Alert>
      ) : null}
    </CardFooter>
  );
}
