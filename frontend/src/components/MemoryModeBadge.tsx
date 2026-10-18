import { ExclamationTriangleIcon } from "@heroicons/react/24/outline";
import { Badge } from "@/components/ui/badge";

/** Avertissement sobre : les données ne survivent pas à un redémarrage du serveur. */
export function MemoryModeBadge() {
  return (
    <Badge
      variant="outline"
      role="status"
      title="Les données sont perdues au redémarrage du serveur."
    >
      <ExclamationTriangleIcon data-icon="inline-start" aria-hidden="true" />
      Mode mémoire
    </Badge>
  );
}
