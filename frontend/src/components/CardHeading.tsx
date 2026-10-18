import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { CardAction, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** En-tête commun des cartes : icône, titre (`text-sm font-semibold`), pastille d'état, description. */
export function CardHeading({
  icon,
  title,
  badge,
  badgeLabel,
  live = false,
  description,
}: {
  icon: ReactNode;
  title: ReactNode;
  badge?: string | null;
  /** Lu aux lecteurs d'écran avant la pastille. */
  badgeLabel?: string;
  /** La pastille est un statut annoncé quand il change (exécution). */
  live?: boolean;
  description?: string | null;
}) {
  return (
    <CardHeader>
      <CardTitle className="flex items-center gap-2 font-sans text-sm font-semibold">
        {icon}
        {title}
      </CardTitle>
      {badge ? (
        <CardAction>
          <Badge variant="secondary" role={live ? "status" : undefined}>
            {badgeLabel ? <span className="sr-only">{badgeLabel} : </span> : null}
            {badge}
          </Badge>
        </CardAction>
      ) : null}
      {description ? (
        <CardDescription className="whitespace-pre-wrap">{description}</CardDescription>
      ) : null}
    </CardHeader>
  );
}
