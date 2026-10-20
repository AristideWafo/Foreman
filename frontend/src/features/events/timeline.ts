import type { CardData, ExecutionCardData, ProjectEvent } from "../../api/events";

export interface Author {
  id: string;
  name: string;
}

export type TimelineItem =
  | {
      key: string;
      kind: "message";
      role: "user" | "assistant";
      text: string;
      /** Auteur des messages utilisateur récents ; absent pour l'assistant et l'ancien historique. */
      author?: Author;
    }
  | {
      key: string;
      kind: "card";
      card: CardData;
      logs: StepLogs;
      /** Exécution de ce plan, repliée dans sa carte par `foldExecutions`. */
      execution?: { card: ExecutionCardData; logs: StepLogs };
    }
  /** Activité d'un tour : réflexion en cours, puis outils utilisés (déduits des événements du contrat). */
  | { key: string; kind: "trace"; status: "running" | "done" | "error"; tools: string[] }
  | { key: string; kind: "error"; message: string };

/** Lignes de journal par numéro d'étape (flux `execution_log`, filtré par la gateway côté serveur). */
export type StepLogs = Readonly<Record<number, readonly string[]>>;

/** Bornes côté client, en plus de celles du contrat (≤50 lignes de ≤500 caractères par événement). */
const MAX_LINES_PER_STEP = 200;
const MAX_LINE_LENGTH = 500;

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

function isAuthor(value: unknown): value is Author {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "string" &&
    "name" in value &&
    typeof value.name === "string"
  );
}

/** Auteurs distincts des messages, dans l'ordre de première apparition. */
export function participants(items: readonly TimelineItem[]): Author[] {
  const seen = new Map<string, Author>();
  for (const item of items) {
    if (item.kind === "message" && item.author && !seen.has(item.author.id)) {
      seen.set(item.author.id, item.author);
    }
  }
  return [...seen.values()];
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

/** Les cartes plan et exécution doivent avoir la forme minimale que le rendu suppose ; les autres `kind` passent. */
function hasExpectedShape(card: CardData): boolean {
  switch (card.kind) {
    case "plan":
      return Array.isArray(card.steps);
    case "execution":
      return (
        Array.isArray(card.steps) &&
        Array.isArray(card.resources) &&
        typeof card.budget === "object" &&
        card.budget !== null
      );
    case "clarification":
      return Array.isArray(card.questions);
    default:
      return true;
  }
}

/** `execution_step` et `execution_log` visent la carte d'exécution, jamais la carte plan. */
function findExecutionCard(items: TimelineItem[], cardId: unknown): number {
  return items.findIndex(
    (item) =>
      item.kind === "card" && item.card.kind === "execution" && item.card.card_id === cardId,
  );
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
          {
            key,
            kind: "message",
            role: event.data.role,
            text: event.data.text,
            ...(isAuthor(event.data.author) ? { author: event.data.author } : {}),
          },
        ],
      };
    case "card": {
      const card = event.data;
      if (typeof card.card_id !== "string" || !hasExpectedShape(card)) return state;
      const index = state.items.findIndex(
        (item) => item.kind === "card" && item.card.card_id === card.card_id,
      );
      const previous = state.items[index];
      if (previous?.kind !== "card") {
        // Une carte de plan est le résultat de l'outil `propose_plan` : on l'ajoute à la trace du tour.
        const items = card.kind === "plan" ? addTool(state.items, "propose_plan") : state.items;
        return { ...state, items: [...items, { key, kind: "card", card, logs: {} }] };
      }
      // Même `card_id` : la carte (réémise entière) remplace la précédente, à la même place.
      // Les logs, qui arrivent à part, sont conservés.
      const items = state.items.slice();
      items[index] = { key: previous.key, kind: "card", card, logs: previous.logs };
      return { ...state, items };
    }
    case "execution_step": {
      const { card_id, step, status } = event.data;
      const index = findExecutionCard(state.items, card_id);
      const target = state.items[index];
      // Carte inconnue ou qui n'est pas l'exécution : événement ignoré.
      if (target?.kind !== "card" || target.card.kind !== "execution") return state;
      const card = {
        ...target.card,
        steps: target.card.steps.map((s) => (s.step === step ? { ...s, status } : s)),
      };
      const items = state.items.slice();
      items[index] = { ...target, card };
      return { ...state, items };
    }
    case "execution_log": {
      const { card_id, step, lines } = event.data;
      const index = findExecutionCard(state.items, card_id);
      const target = state.items[index];
      if (target?.kind !== "card" || typeof step !== "number" || !Array.isArray(lines)) {
        return state;
      }
      const fresh = lines
        .filter((line): line is string => typeof line === "string")
        .slice(0, 50)
        .map((line) => line.slice(0, MAX_LINE_LENGTH));
      if (fresh.length === 0) return state;
      const merged = [...(target.logs[step] ?? []), ...fresh].slice(-MAX_LINES_PER_STEP);
      const items = state.items.slice();
      items[index] = { ...target, logs: { ...target.logs, [step]: merged } };
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

/**
 * Vue d'affichage : l'exécution d'un plan est montrée dans la carte de ce plan (mêmes étapes, statuts et
 * journaux en direct), pas dans une seconde carte. Une exécution sans plan connu reste une carte à part.
 */
export function foldExecutions(items: TimelineItem[]): TimelineItem[] {
  const executions = new Map<string, { card: ExecutionCardData; logs: StepLogs }>();
  for (const item of items) {
    if (item.kind === "card" && item.card.kind === "execution") {
      executions.set(item.card.plan_card_id, { card: item.card, logs: item.logs });
    }
  }
  const folded: TimelineItem[] = [];
  for (const item of items) {
    if (item.kind !== "card") {
      folded.push(item);
    } else if (item.card.kind === "execution") {
      const planCardId = item.card.plan_card_id;
      const hasPlan = items.some((i) => i.kind === "card" && i.card.card_id === planCardId);
      if (!hasPlan) folded.push(item);
    } else {
      const execution = executions.get(item.card.card_id);
      folded.push(execution ? { ...item, execution } : item);
    }
  }
  return folded;
}
