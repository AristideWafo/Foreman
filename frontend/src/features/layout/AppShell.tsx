import { Outlet, useMatch } from "react-router-dom";
import { AppSidebar } from "@/components/AppSidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useMe } from "../cards/useMe";
import { useMemoryMode } from "../health/useHealth";
import { useProjects } from "../projects/useProjects";

/** Cadre de l'application : double barre latérale + contenu de la page. */
export function AppShell() {
  const { projects } = useProjects();
  const memoryMode = useMemoryMode();
  const me = useMe();
  const match = useMatch("/projects/:projectId");
  const activeProjectId = match?.params.projectId ?? null;
  return (
    <TooltipProvider>
      <SidebarProvider
        className="h-svh"
        style={{ "--sidebar-width": "20rem" } as React.CSSProperties}
      >
        <AppSidebar
          projects={projects}
          activeProjectId={activeProjectId}
          homeActive={activeProjectId === null}
          memoryMode={memoryMode}
          me={me}
        />
        <SidebarInset className="min-h-0 overflow-hidden">
          <Outlet />
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
