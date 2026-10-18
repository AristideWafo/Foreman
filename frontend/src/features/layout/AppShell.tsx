import { Outlet, useMatch } from "react-router-dom";
import { AppSidebar } from "@/components/AppSidebar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useRecentProjects } from "../projects/useRecentProjects";

/** Cadre de l'application : double barre latérale + contenu de la page. */
export function AppShell() {
  const { projects } = useRecentProjects();
  const match = useMatch("/projects/:projectId");
  const activeProjectId = match?.params.projectId ?? null;
  return (
    <TooltipProvider>
      <SidebarProvider style={{ "--sidebar-width": "20rem" } as React.CSSProperties}>
        <AppSidebar
          projects={projects}
          activeProjectId={activeProjectId}
          homeActive={activeProjectId === null}
        />
        <SidebarInset>
          <Outlet />
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
