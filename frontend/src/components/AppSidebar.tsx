import {
  ArrowRightStartOnRectangleIcon,
  Cog6ToothIcon,
  FolderIcon,
  HomeIcon,
  InformationCircleIcon,
  PlusIcon,
  ShieldCheckIcon,
  ServerStackIcon,
  UserCircleIcon,
  UsersIcon,
} from "@heroicons/react/24/outline";
import type { ComponentType, SVGProps } from "react";
import { Link } from "react-router-dom";
import { NativeSelect } from "@/components/NativeSelect";
import { LinkButton } from "@/components/LinkButton";
import { MemoryModeBadge } from "@/components/MemoryModeBadge";
import { ROLE_LABELS, UserRoleBadge, type UserRole } from "@/components/UserRoleBadge";
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
  teamId: string;
}

interface AppSidebarProps {
  projects: SidebarProject[];
  /** Projet ouvert (surligné), `null` sur l'accueil. */
  activeProjectId: string | null;
  homeActive: boolean;
  /** Page d'administration ouverte. */
  adminActive?: boolean;
  /** Le serveur n'a pas de base : badge d'avertissement en pied de panneau. */
  memoryMode?: boolean;
  /** Utilisateur courant (`/api/me`), `undefined` tant qu'il n'est pas connu. */
  me?: { name: string; role: UserRole };
  /** Absent hors session : pas de bouton de déconnexion. */
  onLogout?: () => void;
  /** Aide visuelle : le serveur décide de l'accès à l'administration. */
  canAdmin?: boolean;
  /** Équipes de l'utilisateur ; le filtre n'apparaît qu'à partir de deux équipes. */
  teams?: { id: string; name: string }[];
  /** Équipe filtrée, `""` pour toutes. */
  teamFilter?: string;
  onTeamFilter?: (teamId: string) => void;
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
  adminActive = false,
  memoryMode = false,
  me,
  onLogout,
  canAdmin = false,
  teams = [],
  teamFilter = "",
  onTeamFilter,
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
                {canAdmin ? (
                  <RailItem
                    label="Administration"
                    icon={ShieldCheckIcon}
                    to="/admin"
                    active={adminActive}
                  />
                ) : null}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        </SidebarContent>
        <SidebarFooter>
          <SidebarMenu>
            <RailItem label="Informations" icon={InformationCircleIcon} />
            <RailItem label="Paramètres" icon={Cog6ToothIcon} />
            <RailItem
              label={me ? `${me.name}, ${ROLE_LABELS[me.role]}` : "Compte"}
              icon={UserCircleIcon}
            />
            {onLogout ? (
              <SidebarMenuItem>
                <SidebarMenuButton
                  tooltip={{ children: "Se déconnecter", hidden: false }}
                  className={RAIL_BUTTON}
                  onClick={onLogout}
                >
                  <ArrowRightStartOnRectangleIcon />
                  <span className="sr-only">Se déconnecter</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ) : null}
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
            {teams.length > 1 ? (
              <div className="px-2 pb-2">
                <NativeSelect
                  aria-label="Filtrer par équipe"
                  value={teamFilter}
                  onChange={(e) => onTeamFilter?.(e.target.value)}
                >
                  <option value="">Toutes les équipes</option>
                  {teams.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            ) : null}
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
        <SidebarFooter className="gap-3 border-t p-4">
          {memoryMode && <MemoryModeBadge />}
          <UserRoleBadge me={me} />
        </SidebarFooter>
      </Sidebar>
    </Sidebar>
  );
}
