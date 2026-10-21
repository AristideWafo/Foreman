import { CubeIcon, GlobeAltIcon, ServerIcon } from "@heroicons/react/24/outline";
import { brandLogo } from "./brandLogos";

/** Repli Heroicons quand aucun logo n'existe pour la marque. */
const FALLBACK: Record<string, React.ReactElement> = {
  dns: <GlobeAltIcon aria-hidden="true" />,
  server: <ServerIcon aria-hidden="true" />,
};

/** Logo de marque d'une ressource (décoratif), ou icône Heroicons si la marque est inconnue. */
export function BrandLogo({ provider, resourceType }: { provider: string; resourceType: string }) {
  const src = brandLogo(provider, resourceType);
  if (src) {
    const invert = provider === "anthropic" ? " dark:invert" : "";
    return (
      <img src={src} alt="" aria-hidden="true" className={`size-[1.125rem] shrink-0${invert}`} />
    );
  }
  return FALLBACK[provider] ?? <CubeIcon aria-hidden="true" />;
}
