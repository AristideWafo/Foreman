import { Outlet, useMatch } from "react-router-dom";
import { AppSidebar, PERSONAL } from "@/components/AppSidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { canAdminister } from "../admin/AdminPage";
import { useLogout } from "../auth/useLogout";
import { useMe } from "../cards/useMe";
import { useMemoryMode } from "../health/useHealth";
import { useProjects } from "../projects/useProjects";
import { useTeamSelection } from "../projects/useTeamSelection";

/** Cadre de l'application : double barre latérale + contenu de la page. */
export function AppShell() {
  const { projects } = useProjects();
  const memoryMode = useMemoryMode();
  const me = useMe();
  const logout = useLogout();
  const teams = me?.teams ?? [];
  const { stored, set } = useTeamSelection();
  const teamOf = (p: { teamId: string }) =>
    teams.some((t) => t.id === p.teamId) ? p.teamId : PERSONAL;
  // Une équipe disparue de `/me` est retirée ; tant que `/me` manque, on ne retire rien.
  const selected = me
    ? stored.filter((id) => id === PERSONAL || teams.some((t) => t.id === id))
    : stored;
  const visible = selected.length ? projects.filter((p) => selected.includes(teamOf(p))) : projects;
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
          teams={teams}
          hasPersonal={projects.some((p) => teamOf(p) === PERSONAL)}
          selectedTeams={selected}
          onSelectTeams={set}
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
