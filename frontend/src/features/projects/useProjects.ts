import { useQuery } from "@tanstack/react-query";
import { listProjects } from "../../api/client";

export const PROJECTS_KEY = ["projects"] as const;

/** Projets connus du serveur (base de données), du plus récent au plus ancien. */
export function useProjects() {
  const query = useQuery({ queryKey: PROJECTS_KEY, queryFn: listProjects });
  const projects = (query.data ?? []).map((p) => ({
    id: p.id,
    title: p.title || "Sans titre",
    teamId: p.team_id,
  }));
  return { projects, isLoading: query.isPending };
}
