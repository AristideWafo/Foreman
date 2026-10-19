import type { ResourceRef } from "../../api/events";
import { ExternalLink } from "@/components/ExternalLink";
import { Badge } from "@/components/ui/badge";

/** Ressources (attendues ou créées) : nom, fournisseur, type ; le nom est un lien si l'API en donne un. */
export function ResourceList({
  resources,
  linked = false,
}: {
  resources: readonly (Omit<ResourceRef, "url" | "reused"> & {
    url?: string | null;
    reused?: boolean | null;
  })[];
  linked?: boolean;
}) {
  return (
    <ul className="flex flex-col">
      {resources.map((r, index) => (
        <li key={`${index}:${r.provider}/${r.resource_type}/${r.name}`}>
          {linked ? <ExternalLink href={r.url}>{r.name}</ExternalLink> : r.name}
          <span className="text-xs text-muted-foreground">
            {" "}
            · {r.provider} · {r.resource_type}
          </span>
          {r.reused === true ? (
            <>
              {" "}
              <Badge variant="secondary">déjà présente</Badge>
            </>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
