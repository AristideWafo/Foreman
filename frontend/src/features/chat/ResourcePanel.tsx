import {
  ArrowPathIcon,
  ArrowUturnLeftIcon,
  CheckBadgeIcon,
  CheckCircleIcon,
  CubeIcon,
  EllipsisHorizontalCircleIcon,
  ExclamationCircleIcon,
  ListBulletIcon,
} from "@heroicons/react/24/outline";
import { BrandLogo } from "@/components/BrandLogo";
import { CollapsibleSection } from "@/components/CollapsibleSection";
import { ExternalLink } from "@/components/ExternalLink";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "cn";
import { executionStateLabel, planStatusLabel, type Icon } from "../cards/vocabulary";
import {
  RESOURCE_STATUSES,
  type ProjectStatus,
  type ResourceStatus,
  type ResourceView,
} from "../events/status";

/**
 * Présentation des six statuts : le sens ne repose pas sur la couleur (icône + libellé lu par les lecteurs
 * d'écran). Une ressource ciblée (prévue, pas encore faite) ou annulée est grisée ; les autres sont en couleur.
 */
const STATUS: Record<ResourceStatus, { label: string; Icon: Icon; row: string; icon: string }> = {
  targeted: {
    label: "Ciblée",
    Icon: EllipsisHorizontalCircleIcon,
    row: "opacity-50 grayscale",
    icon: "",
  },
  running: {
    label: "En cours",
    Icon: ArrowPathIcon,
    row: "font-medium",
    icon: "motion-safe:animate-spin",
  },
  created: { label: "Créée", Icon: CheckCircleIcon, row: "", icon: "text-primary" },
  reused: { label: "Déjà présente", Icon: CheckBadgeIcon, row: "", icon: "text-primary" },
  failed: { label: "En échec", Icon: ExclamationCircleIcon, row: "", icon: "text-destructive" },
  cancelled: {
    label: "Annulée",
    Icon: ArrowUturnLeftIcon,
    row: "opacity-50 grayscale line-through",
    icon: "",
  },
};

function ResourceRow({ resource }: { resource: ResourceView }) {
  const status = STATUS[resource.status];
  return (
    <li className={cn("flex items-start gap-2 py-1 text-sm", status.row)}>
      <span className="mt-0.5 flex shrink-0">
        <BrandLogo provider={resource.provider} resourceType={resource.resource_type} />
      </span>
      <span className="min-w-0 flex-1 break-words">
        <ExternalLink href={resource.url}>{resource.name}</ExternalLink>
        <span className="block text-xs text-muted-foreground">
          {resource.provider} · {resource.resource_type}
        </span>
      </span>
      <span className="mt-0.5 flex shrink-0" data-status={resource.status}>
        <status.Icon aria-hidden="true" className={status.icon} />
        <span className="sr-only">{status.label}</span>
      </span>
    </li>
  );
}

function Summary({ summary }: { summary: NonNullable<ProjectStatus["summary"]> }) {
  const planStatus = planStatusLabel(summary.planStatus);
  const executionState = executionStateLabel(summary.executionState);
  return (
    // Seul le résumé est annoncé aux lecteurs d'écran, pas toute la liste.
    <div role="status" aria-live="polite" className="flex flex-col gap-2 px-1 text-sm">
      <p className="font-medium break-words">{summary.title ?? "Exécution"}</p>
      <p className="flex flex-wrap items-center gap-1">
        {summary.environment ? <Badge variant="outline">{summary.environment}</Badge> : null}
        {planStatus ? <Badge variant="secondary">{planStatus}</Badge> : null}
        {executionState ? <Badge variant="secondary">{executionState}</Badge> : null}
      </p>
      {summary.currentStep ? (
        <p className="text-muted-foreground">
          <span className="sr-only">Étape en cours : </span>
          {summary.currentStep}
        </p>
      ) : null}
      <ul aria-label="Ressources par statut" className="flex flex-wrap gap-1">
        {RESOURCE_STATUSES.filter((s) => summary.counts[s] > 0).map((s) => {
          const { Icon, label, row, icon } = STATUS[s];
          return (
            <li key={s}>
              <Badge variant="outline" className={cn(row, "[&>svg]:size-3!")}>
                <Icon aria-hidden="true" className={icon} />
                {summary.counts[s]}
                <span className="sr-only"> {label.toLowerCase()}</span>
              </Badge>
            </li>
          );
        })}
      </ul>
      {summary.lastAction ? (
        <p className="font-mono text-xs break-words text-muted-foreground">
          <span className="sr-only">Dernière action : </span>
          {summary.lastAction}
        </p>
      ) : null}
    </div>
  );
}

/** Contenu de la barre latérale des ressources (flottante sur grand écran, tiroir sur mobile). */
export function ResourcePanel({
  status,
  connecting,
}: {
  status: ProjectStatus;
  connecting: boolean;
}) {
  if (connecting) {
    return (
      <div className="flex flex-col gap-2 p-3" role="status" aria-label="Chargement des ressources">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    );
  }
  if (!status.summary) {
    return (
      <p className="p-3 text-sm text-muted-foreground">
        Aucun plan pour l'instant. Les ressources apparaîtront ici.
      </p>
    );
  }
  return (
    <ScrollArea className="min-h-0 flex-1">
      <div className="flex flex-col gap-3 p-3">
        <CollapsibleSection title="Résumé" icon={<ListBulletIcon />}>
          <Summary summary={status.summary} />
        </CollapsibleSection>
        <CollapsibleSection title="Ressources" icon={<CubeIcon />}>
          {status.resources.length === 0 ? (
            <p className="px-1 text-sm text-muted-foreground">Ce plan ne crée aucune ressource.</p>
          ) : (
            <ul className="flex flex-col px-1">
              {status.resources.map((r, index) => (
                <ResourceRow
                  key={`${index}:${r.provider}/${r.resource_type}/${r.name}`}
                  resource={r}
                />
              ))}
            </ul>
          )}
        </CollapsibleSection>
      </div>
    </ScrollArea>
  );
}
