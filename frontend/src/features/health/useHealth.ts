import { useQuery } from "@tanstack/react-query";
import { getPersistence } from "../../api/client";

export const HEALTH_KEY = ["health", "persistence"] as const;

/** Vrai seulement si le serveur répond `persistence = "memory"` ; en cas d'échec, faux (rien à afficher). */
export function useMemoryMode(): boolean {
  const query = useQuery({ queryKey: HEALTH_KEY, queryFn: getPersistence, retry: false });
  return query.data === "memory";
}
