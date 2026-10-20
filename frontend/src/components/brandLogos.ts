import docker from "@/assets/logos/docker.svg";
import gitlab from "@/assets/logos/gitlab.svg";

/**
 * Logos svgl (svgl.app) copiés dans `src/assets/logos/`, jamais chargés depuis le réseau.
 * Ces deux marques ont une seule variante colorée, lisible en clair comme en sombre.
 * Le type de ressource prime sur le fournisseur (un projet « server » tourne sous Docker Compose).
 */
const BY_TYPE: Record<string, string> = { server_project: docker };
const BY_PROVIDER: Record<string, string> = { gitlab };

export function brandLogo(provider: string, resourceType: string): string | undefined {
  return BY_TYPE[resourceType] ?? BY_PROVIDER[provider];
}
