import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

export type UserRole = "developer" | "team_admin" | "org_admin";

export const ROLE_LABELS: Record<UserRole, string> = {
  developer: "Développeur",
  team_admin: "Admin d'équipe",
  org_admin: "Admin d'organisation",
};

interface UserRoleBadgeProps {
  /** Absent tant que `/api/me` charge (ou a échoué). */
  me?: { name: string; role: UserRole };
}

/** Nom et rôle de l'utilisateur ; un squelette discret pendant le chargement. */
export function UserRoleBadge({ me }: UserRoleBadgeProps) {
  if (!me) return <Skeleton className="h-5 w-32" aria-hidden="true" />;
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="truncate text-sm font-medium">{me.name}</span>
      <Badge variant="secondary">{ROLE_LABELS[me.role]}</Badge>
    </div>
  );
}
