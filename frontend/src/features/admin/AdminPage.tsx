import type { Me } from "../../api/client";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMe } from "../cards/useMe";
import { InvitationsTab } from "./InvitationsTab";
import { MembersTab } from "./MembersTab";
import { TeamsTab } from "./TeamsTab";

/** Aide visuelle uniquement : le serveur refuse (403) ce que le rôle n'autorise pas. */
export function canAdminister(me: Pick<Me, "role" | "teams"> | undefined): boolean {
  return (
    me?.role === "org_admin" ||
    (me?.teams ?? []).some((t) => t.role === "team_admin" || t.role === "org_admin")
  );
}

export function AdminPage() {
  const me = useMe();
  return (
    <>
      <PageHeader>Administration</PageHeader>
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 overflow-y-auto px-4 py-8">
        {!me ? (
          <Skeleton className="h-24 w-full" role="status" aria-label="Chargement" />
        ) : !canAdminister(me) ? (
          <p>Cette page est réservée aux administrateurs.</p>
        ) : (
          <Tabs defaultValue="teams">
            <TabsList>
              <TabsTrigger value="teams">Équipes</TabsTrigger>
              <TabsTrigger value="members">Membres</TabsTrigger>
              <TabsTrigger value="invitations">Invitations</TabsTrigger>
            </TabsList>
            <TabsContent value="teams" className="pt-4">
              <TeamsTab isOrgAdmin={me.role === "org_admin"} />
            </TabsContent>
            <TabsContent value="members" className="pt-4">
              <MembersTab isOrgAdmin={me.role === "org_admin"} />
            </TabsContent>
            <TabsContent value="invitations" className="pt-4">
              <InvitationsTab role={me.role} />
            </TabsContent>
          </Tabs>
        )}
      </main>
    </>
  );
}
