import {
  Cog6ToothIcon,
  FolderIcon,
  HomeIcon,
  InformationCircleIcon,
  PlusIcon,
  ServerStackIcon,
  UserCircleIcon,
  UsersIcon,
} from "@heroicons/react/24/outline";
import type { ComponentType, SVGProps } from "react";
import { Link } from "react-router-dom";
import { LinkButton } from "@/components/LinkButton";
import { MemoryModeBadge } from "@/components/MemoryModeBadge";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
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
  /** Le serveur n'a pas de base : badge d'avertissement en pied de panneau. */
  memoryMode?: boolean;
}

type Icon = ComponentType<SVGProps<SVGSVGElement>>;

// Même classes pour toutes les entrées du rail : icône centrée, donc alignée.
const RAIL_BUTTON = "justify-center px-0";

function RailItem({
  label,
  icon: IconComponent,
  active = false,
  to,
}: {
  label: string;
  icon: Icon;
  active?: boolean;
  /** Sans `to`, l'entrée est désactivée : la page n'existe pas encore. */
  to?: string;
}) {
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        tooltip={{ children: to ? label : `${label} (bientôt)`, hidden: false }}
        isActive={active}
        disabled={!to}
        className={RAIL_BUTTON}
        render={to ? <Link to={to} /> : undefined}
      >
        <IconComponent />
        <span className="sr-only">{label}</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

/** Double barre latérale : rail d'icônes (navigation) + panneau (projets). */
export function AppSidebar({
  projects,
  activeProjectId,
  homeActive,
  memoryMode = false,
}: AppSidebarProps) {
  return (
    <Sidebar collapsible="icon" className="overflow-hidden *:data-[sidebar=sidebar]:flex-row">
      <Sidebar collapsible="none" className="w-[calc(var(--sidebar-width-icon)+1px)]! border-r">
        <SidebarHeader>
          <SidebarMenu>
            <RailItem label="Foreman" icon={ServerStackIcon} to="/" />
          </SidebarMenu>
        </SidebarHeader>
        <SidebarContent>
          <SidebarGroup>
            <SidebarGroupContent>
              <SidebarMenu>
                <RailItem label="Accueil" icon={HomeIcon} to="/" active={homeActive} />
                <RailItem label="Projets" icon={FolderIcon} to="/" active={!homeActive} />
                <RailItem label="Équipes" icon={UsersIcon} />
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter>
          <SidebarMenu>
            <RailItem label="Informations" icon={InformationCircleIcon} />
            <RailItem label="Paramètres" icon={Cog6ToothIcon} />
            <RailItem label="Compte" icon={UserCircleIcon} />
          </SidebarMenu>
        </SidebarFooter>
      </Sidebar>

      <Sidebar collapsible="none" className="hidden min-w-0 flex-1 md:flex">
        <SidebarHeader className="gap-3 border-b p-4">
          <span className="text-sm font-semibold">Foreman</span>
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
        {memoryMode && (
          <SidebarFooter className="border-t p-4">
            <MemoryModeBadge />
          </SidebarFooter>
        )}
      </Sidebar>
    </Sidebar>
  );
}
