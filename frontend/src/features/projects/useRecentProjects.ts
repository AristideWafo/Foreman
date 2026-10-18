import { useCallback, useSyncExternalStore } from "react";

export interface RecentProject {
  id: string;
  title: string;
}

const STORAGE_KEY = "foreman.recent-projects";
const MAX_PROJECTS = 20;
const listeners = new Set<() => void>();
let cache: { raw: string | null; value: RecentProject[] } = { raw: null, value: [] };

function read(): RecentProject[] {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(STORAGE_KEY);
  } catch {
    // Stockage indisponible (navigation privée) : liste vide.
  }
  // Même référence tant que le contenu ne change pas (exigé par useSyncExternalStore).
  if (raw === cache.raw) return cache.value;
  let value: RecentProject[] = [];
  try {
    const parsed: unknown = raw === null ? [] : JSON.parse(raw);
    if (Array.isArray(parsed)) {
      value = parsed.filter(
        (p): p is RecentProject =>
          typeof p === "object" &&
          p !== null &&
          typeof (p as RecentProject).id === "string" &&
          typeof (p as RecentProject).title === "string",
      );
    }
  } catch {
    // JSON invalide : liste vide.
  }
  cache = { raw, value };
  return value;
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Projets créés dans ce navigateur. Le serveur n'expose pas (encore) de liste de projets :
 * la liste est locale et peut contenir un projet que le serveur a oublié (redémarrage).
 */
export function useRecentProjects() {
  const projects = useSyncExternalStore(subscribe, read);
  const add = useCallback((project: RecentProject) => {
    const next = [project, ...read().filter((p) => p.id !== project.id)].slice(0, MAX_PROJECTS);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Stockage indisponible : le projet reste utilisable, il n'est juste pas listé.
    }
    listeners.forEach((listener) => listener());
  }, []);
  return { projects, add };
}
