import type { PlanCardData, ProjectEvent } from "../../api/events";

export type TimelineItem =
  | { key: string; kind: "message"; role: "user" | "assistant"; text: string }
  | { key: string; kind: "card"; card: PlanCardData }
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

function applyContent(state: TimelineState, event: ProjectEvent): TimelineState {
  const key = `e${event.seq}`;
  switch (event.type) {
    case "message":
      return {
        ...state,
        items: [
          ...state.items,
          { key, kind: "message", role: event.data.role, text: event.data.text },
        ],
      };
    case "card": {
      const card = event.data;
      const index = state.items.findIndex(
        (item) => item.kind === "card" && item.card.card_id === card.card_id,
      );
      if (index === -1) return { ...state, items: [...state.items, { key, kind: "card", card }] };
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
      // Carte inconnue : événement ignoré.
      if (!target || target.kind !== "card") return state;
      const card = {
        ...target.card,
        steps: target.card.steps.map((s) => (s.step === step ? { ...s, status } : s)),
      };
      const items = state.items.slice();
      items[index] = { ...target, card };
      return { ...state, items };
    }
    case "turn_status":
      return { ...state, turnRunning: event.data.status === "running" };
    case "error":
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
 * Un type inconnu consomme quand même son `seq`, pour ne pas faire croire à un trou.
 */
export function applyEvent(state: TimelineState, event: ProjectEvent): TimelineState {
  if (event.seq <= state.lastSeq) return state;
  const base = event.seq > state.lastSeq + 1 ? initialTimeline : state;
  return { ...applyContent(base, event), lastSeq: event.seq };
}
