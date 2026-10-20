import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";

/** Chargement, échec ou liste vide d'une requête ; `null` quand il y a des données à afficher. */
export function QueryStatus({
  isPending,
  isError,
  empty,
  emptyText,
}: {
  isPending: boolean;
  isError: boolean;
  empty: boolean;
  emptyText: string;
}) {
  if (isPending) return <Skeleton className="h-16 w-full" aria-label="Chargement" role="status" />;
  if (isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>
          Chargement impossible. Votre rôle ne le permet peut-être pas, ou le service est
          indisponible.
        </AlertDescription>
      </Alert>
    );
  }
  return empty ? <p className="text-sm">{emptyText}</p> : null;
}

/** Erreur d'une action (mutation), annoncée aux lecteurs d'écran. */
export function ActionError({ message }: { message: string | null }) {
  return message ? (
    <Alert variant="destructive">
      <AlertDescription>{message}</AlertDescription>
    </Alert>
  ) : null;
}
