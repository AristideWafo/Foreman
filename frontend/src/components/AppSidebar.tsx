import { FolderIcon, HomeIcon, PlusIcon, ServerStackIcon } from "@heroicons/react/24/outline";
import { Link } from "react-router-dom";
import { LinkButton } from "@/components/LinkButton";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
} from "@/components/ui/sidebar";

export interface SidebarProject {
  id: string;
  title: string;
}

interface AppSidebarProps {
  projects: SidebarProject[];
  /** Projet ouvert (surligné), `null` sur l'accueil. */
  activeProjectId: string | null;
  homeActive: boolean;
}

/** Double barre latérale : rail d'icônes (navigation) + panneau (projets). */
export function AppSidebar({ projects, activeProjectId, homeActive }: AppSidebarProps) {
  return (
    <Sidebar collapsible="icon" className="overflow-hidden *:data-[sidebar=sidebar]:flex-row">
      <Sidebar collapsible="none" className="w-[calc(var(--sidebar-width-icon)+1px)]! border-r">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton
                size="lg"
                className="md:h-8 md:p-0"
                tooltip={{ children: "Foreman", hidden: false }}
                render={<Link to="/" />}
              >
                <ServerStackIcon />
                <span className="sr-only">Foreman</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent className="px-1.5 md:px-0">
              <SidebarMenu>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    tooltip={{ children: "Accueil", hidden: false }}
                    isActive={homeActive}
                    className="px-2.5 md:px-2"
                    render={<Link to="/" />}
                  >
                    <HomeIcon />
                    <span>Accueil</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                <SidebarMenuItem>
                  <SidebarMenuButton
                    tooltip={{ children: "Projets", hidden: false }}
                    isActive={!homeActive}
                    className="px-2.5 md:px-2"
                  >
                    <FolderIcon />
                    <span>Projets</span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
      </Sidebar>

      <Sidebar collapsible="none" className="hidden min-w-0 flex-1 md:flex">
        <SidebarHeader className="gap-3 border-b p-4">
          <div className="flex w-full items-center justify-between">
            <span className="text-sm font-semibold">Foreman</span>
            <SidebarTrigger />
          </div>
          <LinkButton to="/" className="w-full">
            Nouveau projet
          </LinkButton>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupLabel>Projets</SidebarGroupLabel>
            <SidebarGroupAction render={<Link to="/" />} title="Nouveau projet">
              <PlusIcon />
              <span className="sr-only">Nouveau projet</span>
            </SidebarGroupAction>
            <SidebarGroupContent>
              {projects.length === 0 ? (
                <p className="px-2 py-1.5 text-sm">Aucun projet pour l'instant.</p>
              ) : (
                <SidebarMenu>
                  {projects.map((project) => (
                    <SidebarMenuItem key={project.id}>
                      <SidebarMenuButton
                        isActive={project.id === activeProjectId}
                        render={<Link to={`/projects/${project.id}`} />}
                      >
                        <FolderIcon />
                        <span className="truncate">{project.title}</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              )}
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
      </Sidebar>
    </Sidebar>
  );
}
