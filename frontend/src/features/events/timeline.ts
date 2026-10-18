import type { PlanCardData, ProjectEvent } from "../../api/events";

export type TimelineItem =
  | { key: string; kind: "message"; role: "user" | "assistant"; text: string }
  | { key: string; kind: "card"; card: PlanCardData }
  /** Activité d'un tour : réflexion en cours, puis outils utilisés (déduits des événements du contrat). */
  | { key: string; kind: "trace"; status: "running" | "done" | "error"; tools: string[] }
  | { key: string; kind: "error"; message: string };

export interface TimelineState {
  lastSeq: number;
  items: TimelineItem[];
  turnRunning: boolean;
}

export const initialTimeline: TimelineState = { lastSeq: 0, items: [], turnRunning: false };

/** Vérification minimale de la forme reçue ; tout le reste est ignoré sans exception. */
export function parseEvent(raw: string): ProjectEvent | null {
  try {
    const value: unknown = JSON.parse(raw);
    if (
      typeof value === "object" &&
      value !== null &&
      "seq" in value &&
      typeof value.seq === "number" &&
      Number.isSafeInteger(value.seq) &&
      value.seq > 0 &&
      "type" in value &&
      typeof value.type === "string" &&
      "data" in value &&
      typeof value.data === "object" &&
      value.data !== null
    ) {
      return value as ProjectEvent;
    }
  } catch {
    // JSON invalide : ignoré.
  }
  return null;
}

function lastRunningTrace(items: TimelineItem[]): number {
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];
    if (item?.kind === "trace" && item.status === "running") return i;
  }
  return -1;
}

function addTool(items: TimelineItem[], tool: string): TimelineItem[] {
  const index = lastRunningTrace(items);
  const trace = items[index];
  if (trace?.kind !== "trace" || trace.tools.includes(tool)) return items;
  const next = items.slice();
  next[index] = { ...trace, tools: [...trace.tools, tool] };
  return next;
}

/** `running` ouvre une trace ; `completed` et `failed` ferment la trace en cours. */
function updateTrace(items: TimelineItem[], status: string, key: string): TimelineItem[] {
  const index = lastRunningTrace(items);
  if (status === "running") {
    return index === -1 ? [...items, { key, kind: "trace", status: "running", tools: [] }] : items;
  }
  const trace = items[index];
  if (trace?.kind !== "trace") return items;
  const next = items.slice();
  next[index] = { ...trace, status: status === "failed" ? "error" : "done" };
  return next;
}

function applyContent(state: TimelineState, event: ProjectEvent): TimelineState {
  const key = `e${event.seq}`;
  switch (event.type) {
    case "message":
      // Forme inattendue : ignorée (le `seq` est quand même consommé par `applyEvent`).
      if (
        (event.data.role !== "user" && event.data.role !== "assistant") ||
        typeof event.data.text !== "string"
      ) {
        return state;
      }
      return {
        ...state,
        items: [
          ...state.items,
          { key, kind: "message", role: event.data.role, text: event.data.text },
        ],
      };
    case "card": {
      const card = event.data;
      if (typeof card.card_id !== "string") return state;
      const index = state.items.findIndex(
        (item) => item.kind === "card" && item.card.card_id === card.card_id,
      );
      if (index === -1) {
        // Une carte de plan est le résultat de l'outil `propose_plan` : on l'ajoute à la trace du tour.
        const items = card.kind === "plan" ? addTool(state.items, "propose_plan") : state.items;
        return { ...state, items: [...items, { key, kind: "card", card }] };
      }
      // Même `card_id` : la carte remplace la précédente, à la même place.
      const items = state.items.slice();
      items[index] = { key: state.items[index]?.key ?? key, kind: "card", card };
      return { ...state, items };
    }
    case "execution_step": {
      const { card_id, step, status } = event.data;
      const index = state.items.findIndex(
        (item) => item.kind === "card" && item.card.card_id === card_id,
      );
      const target = state.items[index];
      // Carte inconnue, ou d'un `kind` sans étapes (évolution additive) : événement ignoré.
      if (!target || target.kind !== "card") return state;
      if (target.card.kind !== "plan" || !Array.isArray(target.card.steps)) return state;
      const card = {
        ...target.card,
        steps: target.card.steps.map((s) => (s.step === step ? { ...s, status } : s)),
      };
      const items = state.items.slice();
      items[index] = { ...target, card };
      return { ...state, items };
    }
    case "turn_status": {
      const { status } = event.data;
      return {
        ...state,
        turnRunning: status === "running",
        items: updateTrace(state.items, status, key),
      };
    }
    case "error":
      if (typeof event.data.message !== "string") return state;
      return {
        ...state,
        items: [...state.items, { key, kind: "error", message: event.data.message }],
      };
    default:
      // Type inconnu (évolution additive du contrat) : ignoré sans exception.
      return state;
  }
}

/**
 * Applique un événement : dédoublonnage par `seq`, détection d'un trou
 * (seq > dernier + 1 : on repart de l'état reçu, la liste locale est vidée d'abord).
 * Un type inconnu, une version `v` inconnue ou une forme inattendue consomme quand même son `seq`,
 * pour ne pas faire croire à un trou.
 */
export function applyEvent(state: TimelineState, event: ProjectEvent): TimelineState {
  if (event.seq <= state.lastSeq) return state;
  const base = event.seq > state.lastSeq + 1 ? initialTimeline : state;
  // `v` différent de 1 : format incompatible. On consomme le `seq` sans appliquer le contenu.
  if (event.v !== 1) return { ...base, lastSeq: event.seq };
  return { ...applyContent(base, event), lastSeq: event.seq };
}
