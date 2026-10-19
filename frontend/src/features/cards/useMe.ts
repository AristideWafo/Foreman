import { useQuery } from "@tanstack/react-query";
import { getMe } from "../../api/client";

/** Identité et rôle de l'appelant, lus côté serveur. Inconnu (chargement, échec) : pas de bouton de décision. */
export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: getMe, retry: false, staleTime: 60_000 }).data;
}
