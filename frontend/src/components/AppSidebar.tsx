import {
  ArrowRightStartOnRectangleIcon,
  Cog6ToothIcon,
  FolderIcon,
  HomeIcon,
  InformationCircleIcon,
  PlusIcon,
  ShieldCheckIcon,
  UserCircleIcon,
  UsersIcon,
} from "@heroicons/react/24/outline";
import { Fragment, type ComponentType, type SVGProps } from "react";
import { Link } from "react-router-dom";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { BrandMark } from "@/components/BrandMark";
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
  /** Équipes partagées de l'utilisateur ; le sélecteur n'apparaît qu'à partir de deux choix. */
  teams?: { id: string; name: string }[];
  /** Des projets appartiennent à l'équipe personnelle (hors `teams`). */
  hasPersonal?: boolean;
  /** Équipes actives (identifiants de `teams` ou `PERSONAL`), vide pour toutes. */
  selectedTeams?: string[];
  onSelectTeams?: (ids: string[]) => void;
}

/** Identifiant de choix pour l'équipe personnelle (non partagée, absente de `/api/me`). */
export const PERSONAL = "personal";
const ALL = "all";

type Icon = ComponentType<SVGProps<SVGSVGElement>>;

/** Le rail attend une icône SVG : le logo (images) s'y glisse sans changer RailItem. */
const BrandMarkIcon: Icon = () => <BrandMark className="size-5" />;

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
  hasPersonal = false,
  selectedTeams = [],
  onSelectTeams,
}: AppSidebarProps) {
  const choices = hasPersonal ? [...teams, { id: PERSONAL, name: "Personnel" }] : teams;
  // Groupes par équipe dans l'ordre des choix ; un seul groupe : liste à plat.
  const groups = choices
    .map((c) => ({
      ...c,
      items: projects.filter(
        (p) => (teams.some((t) => t.id === p.teamId) ? p.teamId : PERSONAL) === c.id,
      ),
    }))
    .filter((g) => g.items.length > 0);
  const grouped = groups.length > 1;
  return (
    <Sidebar collapsible="icon" className="overflow-hidden *:data-[sidebar=sidebar]:flex-row">
      <Sidebar collapsible="none" className="w-[calc(var(--sidebar-width-icon)+1px)]! border-r">
        <SidebarHeader>
          <SidebarMenu>
            <RailItem label="Foreman" icon={BrandMarkIcon} to="/" />
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
          <span className="flex items-center gap-2 text-sm font-semibold">
            <BrandMark className="size-5" />
            Foreman
          </span>
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
            {choices.length > 1 ? (
              <ToggleGroup
                multiple
                variant="outline"
                size="sm"
                spacing={1}
                aria-label="Équipes actives"
                className="flex-wrap px-2 pb-2"
                value={selectedTeams.length ? selectedTeams : [ALL]}
                onValueChange={(next: string[]) =>
                  // « Toutes » vide la sélection ; cocher une équipe décoche « Toutes ».
                  onSelectTeams?.(
                    next.includes(ALL) && selectedTeams.length > 0
                      ? []
                      : next.filter((id) => id !== ALL),
                  )
                }
              >
                <ToggleGroupItem value={ALL}>Toutes</ToggleGroupItem>
                {choices.map((t) => (
                  <ToggleGroupItem key={t.id} value={t.id}>
                    {t.name}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
            ) : null}
            <SidebarGroupContent>
              {projects.length === 0 ? (
                <p className="px-2 py-1.5 text-sm">Aucun projet pour l'instant.</p>
              ) : (
                <SidebarMenu>
                  {(grouped ? groups : [{ id: "", name: "", items: projects }]).map((g) => (
                    <Fragment key={g.id}>
                      {grouped ? (
                        <li className="px-2 pt-2 text-xs font-medium text-sidebar-foreground/70">
                          {g.name}
                        </li>
                      ) : null}
                      {g.items.map((project) => (
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
                    </Fragment>
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
