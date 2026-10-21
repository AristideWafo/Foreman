import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { describeAdminError } from "../../api/client";
import { IntegrationRow } from "./IntegrationRow";
import { useIntegrations } from "./useAdmin";

/** Onglet « Intégrations » (org_admin) : une ligne par connecteur déclaré par l'API. */
export function IntegrationsTab() {
  const integrations = useIntegrations();
  if (integrations.isPending) {
    return (
      <div className="flex flex-col gap-3" role="status" aria-label="Chargement">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (integrations.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription className="flex flex-wrap items-center gap-3">
          {describeAdminError(integrations.error)}
          <Button variant="outline" size="sm" onClick={() => void integrations.refetch()}>
            Réessayer
          </Button>
        </AlertDescription>
      </Alert>
    );
  }
  if (integrations.data.length === 0) return <p className="text-sm">Aucun connecteur déclaré.</p>;
  return (
    <ul className="flex flex-col gap-4">
      {integrations.data.map((i) => (
        <IntegrationRow key={i.connector} integration={i} />
      ))}
    </ul>
  );
}
