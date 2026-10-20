import { useSyncExternalStore } from "react";

const KEY = "foreman.activeTeams";

// Copie en mémoire : la page fonctionne même si `localStorage` est refusé.
let current: string[] = read();
const listeners = new Set<() => void>();

function read(): string[] {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function set(next: string[]) {
  current = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Stockage indisponible : la sélection vit le temps de la session.
  }
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}

/** Équipes actives mémorisées dans le navigateur ; liste vide = toutes. */
export function useTeamSelection() {
  const stored = useSyncExternalStore(subscribe, () => current);
  return { stored, set };
}
