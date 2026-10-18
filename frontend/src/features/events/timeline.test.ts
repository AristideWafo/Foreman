import { describe, expect, test } from "vitest";
import type { ProjectEvent } from "../../api/events";
import {
  applyEvent,
  foldExecutions,
  initialTimeline,
  parseEvent,
  type TimelineItem,
  type TimelineState,
} from "./timeline";

const base = { v: 1, project_id: "p", turn_id: "t", at: "2026-10-20T09:00:00Z" };

function message(seq: number, text = `m${seq}`): ProjectEvent {
  return { ...base, v: 1, seq, type: "message", data: { role: "user", text } } as ProjectEvent;
}

function card(seq: number, cardId: string, title: string): ProjectEvent {
  return {
    ...base,
    seq,
    type: "card",
    data: {
      card_id: cardId,
      kind: "plan",
      title,
      summary: "s",
      steps: [{ step: 1, title: "a", status: "pending" }],
    },
  } as ProjectEvent;
}

function run(events: ProjectEvent[], from: TimelineState = initialTimeline): TimelineState {
  return events.reduce(applyEvent, from);
}

const texts = (state: TimelineState) =>
  state.items.map((i) => (i.kind === "message" ? i.text : i.kind));

describe("timeline (sémantique du flux, contrat v1)", () => {
  test("rejeu complet après reconnexion : seuls les nouveaux événements sont ajoutés", () => {
    const first = run([message(1), message(2), message(3)]);
    const replayed = run([message(1), message(2), message(3), message(4)], first);
    expect(texts(replayed)).toEqual(["m1", "m2", "m3", "m4"]);
    expect(replayed.lastSeq).toBe(4);
  });

  test("même seq avec un contenu différent : le premier est conservé", () => {
    const state = run([message(1, "premier"), message(1, "autre")]);
    expect(texts(state)).toEqual(["premier"]);
  });

  test("trou dans les seq : l'état repart de ce qui est reçu", () => {
    const state = run([message(1), message(2), message(5, "après le trou")]);
    expect(texts(state)).toEqual(["après le trou"]);
    expect(state.lastSeq).toBe(5);
  });

  test("une carte de même card_id remplace la précédente, à la même place", () => {
    const state = run([message(1), card(2, "c1", "v1"), message(3), card(4, "c1", "v2")]);
    const cards = state.items.filter((i) => i.kind === "card");
    expect(cards).toHaveLength(1);
    const second = state.items[1];
    expect(second?.kind === "card" && second.card.kind === "plan" && second.card.title).toBe("v2");
  });

  const execCard = (seq: number, cardId: string, extra: object = {}): ProjectEvent =>
    ({
      ...base,
      seq,
      type: "card",
      data: {
        card_id: cardId,
        kind: "execution",
        execution_id: "e",
        plan_card_id: "plan",
        state: "running",
        autonomy_level: 1,
        steps: [{ step: 1, title: "a", status: "pending" }],
        budget: { tool_calls_used: 0, tool_calls_max: 5, elapsed_s: 0, max_minutes: 1 },
        resources: [],
        result: null,
        ...extra,
      },
    }) as unknown as ProjectEvent;
  const stepEvent = (seq: number, cardId: string): ProjectEvent =>
    ({
      ...base,
      seq,
      type: "execution_step",
      data: { card_id: cardId, step: 1, status: "running" },
    }) as ProjectEvent;
  const logEvent = (seq: number, cardId: string, lines: unknown): ProjectEvent =>
    ({
      ...base,
      seq,
      type: "execution_log",
      data: { card_id: cardId, step: 1, lines },
    }) as ProjectEvent;
  const cardAt = (state: TimelineState, index: number) => {
    const item = state.items[index];
    return item?.kind === "card" ? item : undefined;
  };

  test("execution_step vise la carte d'exécution ; carte plan ou inconnue : ignoré", () => {
    const state = run([
      card(1, "plan", "t"),
      execCard(2, "exec"),
      stepEvent(3, "exec"),
      stepEvent(4, "plan"),
      stepEvent(5, "inconnue"),
    ]);
    expect(cardAt(state, 0)?.card).toMatchObject({ kind: "plan", steps: [{ status: "pending" }] });
    expect(cardAt(state, 1)?.card).toMatchObject({ steps: [{ status: "running" }] });
    expect(state.items).toHaveLength(2);
    expect(state.lastSeq).toBe(5);
  });

  test("execution_log : lignes ajoutées à la carte d'exécution, bornées, conservées quand la carte est réémise", () => {
    const long = "x".repeat(600);
    const state = run([
      card(1, "plan", "t"),
      execCard(2, "exec"),
      logEvent(3, "exec", ["a", 42, long]),
      logEvent(4, "exec", ["b"]),
      logEvent(5, "plan", ["ignorée"]),
      logEvent(6, "inconnue", ["ignorée"]),
      logEvent(7, "exec", "pas un tableau"),
      execCard(8, "exec", { state: "succeeded" }),
    ]);
    const exec = cardAt(state, 1);
    expect(exec?.logs[1]).toEqual(["a", "x".repeat(500), "b"]);
    expect(exec?.card).toMatchObject({ state: "succeeded" });
    expect(cardAt(state, 0)?.logs).toEqual({});
    expect(state.items).toHaveLength(2);
  });

  test("cartes plan et exécution de forme invalide : ignorées sans exception", () => {
    const state = run([
      card(1, "plan", "t"),
      execCard(2, "exec", { budget: null }),
      execCard(3, "exec2", { steps: "non" }),
    ]);
    expect(state.items).toHaveLength(1);
    expect(state.lastSeq).toBe(3);
  });

  test("champs inconnus d'une carte : ignorés", () => {
    const state = run([execCard(1, "exec", { futur: { a: 1 } })]);
    expect(cardAt(state, 0)?.card).toMatchObject({ kind: "execution", state: "running" });
  });

  test("type inconnu : ignoré mais son seq est consommé (pas de faux trou)", () => {
    const unknown = { ...base, seq: 2, type: "futur", data: {} } as unknown as ProjectEvent;
    const state = run([message(1), unknown, message(3)]);
    expect(texts(state)).toEqual(["m1", "m3"]);
  });

  test("v différent de 1 : contenu ignoré, seq consommé", () => {
    const v2 = { ...message(2, "v2"), v: 2 } as unknown as ProjectEvent;
    const state = run([message(1), v2, message(3)]);
    expect(texts(state)).toEqual(["m1", "m3"]);
  });

  test("forme inattendue ou carte d'un kind sans étapes : aucune exception", () => {
    const badText = {
      ...base,
      seq: 2,
      type: "message",
      data: { role: "user", text: { objet: 1 } },
    } as unknown as ProjectEvent;
    const futureCard = {
      ...base,
      seq: 3,
      type: "card",
      data: { card_id: "f", kind: "tableau", title: "t", summary: "s" },
    } as unknown as ProjectEvent;
    const step = {
      ...base,
      seq: 4,
      type: "execution_step",
      data: { card_id: "f", step: 1, status: "running" },
    } as ProjectEvent;
    expect(() => run([message(1), badText, futureCard, step])).not.toThrow();
    expect(run([message(1), badText, futureCard, step]).lastSeq).toBe(4);
  });

  test("parseEvent : refuse un seq non entier ou nul, accepte une enveloppe valide", () => {
    const raw = (seq: unknown) => JSON.stringify({ ...message(1), seq });
    expect(parseEvent(raw(1.5))).toBeNull();
    expect(parseEvent(raw(0))).toBeNull();
    expect(parseEvent(raw(1))).not.toBeNull();
    expect(parseEvent("pas du json")).toBeNull();
  });

  test("trace d'un tour : réflexion en cours, outil `propose_plan` ajouté par la carte, puis terminée", () => {
    const status = (seq: number, value: "running" | "completed" | "failed"): ProjectEvent =>
      ({ ...base, seq, type: "turn_status", data: { status: value } }) as ProjectEvent;
    const trace = (state: TimelineState) => state.items.find((i) => i.kind === "trace");

    const running = run([message(1), status(2, "running")]);
    expect(trace(running)).toMatchObject({ status: "running", tools: [] });

    const withPlan = run([card(3, "c1", "Plan")], running);
    expect(trace(withPlan)).toMatchObject({ status: "running", tools: ["propose_plan"] });

    const done = run([status(4, "completed")], withPlan);
    expect(trace(done)).toMatchObject({ status: "done", tools: ["propose_plan"] });
    expect(
      run([status(4, "failed")], withPlan).items.find((i) => i.kind === "trace"),
    ).toMatchObject({
      status: "error",
    });
  });
});

test("foldExecutions : l'exécution est repliée dans la carte de son plan", () => {
  const plan = {
    key: "a",
    kind: "card",
    logs: {},
    card: { kind: "plan", card_id: "p", steps: [] },
  };
  const run = {
    key: "b",
    kind: "card",
    logs: { 1: ["ok"] },
    card: { kind: "execution", card_id: "x", plan_card_id: "p", steps: [] },
  };
  const folded = foldExecutions([plan, run] as unknown as TimelineItem[]);
  expect(folded).toHaveLength(1);
  expect(folded[0]).toMatchObject({ key: "a", execution: { logs: { 1: ["ok"] } } });
});
