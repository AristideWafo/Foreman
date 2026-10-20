import { useQuery } from "@tanstack/react-query";
import { getProject } from "../../api/client";

/** Projet vu par l'appelant (`can_approve` calculé par le serveur). Inconnu (chargement, échec) : pas de bouton de validation. */
export function useProject(projectId: string) {
  return useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId),
    retry: false,
    staleTime: 60_000,
  }).data;
}
