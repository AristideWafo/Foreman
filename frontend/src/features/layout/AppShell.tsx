import { useState } from "react";
import { Outlet, useMatch } from "react-router-dom";
import { AppSidebar } from "@/components/AppSidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { canAdminister } from "../admin/AdminPage";
import { useLogout } from "../auth/useLogout";
import { useMe } from "../cards/useMe";
import { useMemoryMode } from "../health/useHealth";
import { useProjects } from "../projects/useProjects";

/** Cadre de l'application : double barre latérale + contenu de la page. */
export function AppShell() {
  const { projects } = useProjects();
  const memoryMode = useMemoryMode();
  const me = useMe();
  const logout = useLogout();
  const [teamFilter, setTeamFilter] = useState("");
  const visible = teamFilter ? projects.filter((p) => p.teamId === teamFilter) : projects;
  const adminActive = useMatch("/admin") !== null;
  const match = useMatch("/projects/:projectId");
  const activeProjectId = match?.params.projectId ?? null;
  return (
    <TooltipProvider>
      <SidebarProvider
        className="h-svh"
        style={{ "--sidebar-width": "20rem" } as React.CSSProperties}
      >
        <AppSidebar
          projects={visible}
          activeProjectId={activeProjectId}
          homeActive={activeProjectId === null && !adminActive}
          adminActive={adminActive}
          canAdmin={canAdminister(me)}
          teams={me?.teams ?? []}
          teamFilter={teamFilter}
          onTeamFilter={setTeamFilter}
          memoryMode={memoryMode}
          me={me}
          // Sans jeton CSRF il n'y a pas de session (modes `none`/`proxy_header`) : rien à fermer.
          onLogout={me?.csrf_token ? () => logout.mutate() : undefined}
        />
        <SidebarInset className="min-h-0 overflow-hidden">
          <Outlet />
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
