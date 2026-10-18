import { describe, expect, test } from "vitest";
import type { ProjectEvent } from "../../api/events";
import { applyEvent, initialTimeline, parseEvent, type TimelineState } from "./timeline";

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
    expect(state.items[1]?.kind === "card" && state.items[1].card.title).toBe("v2");
  });

  test("execution_step : met à jour l'étape, et ignore une carte inconnue", () => {
    const step = (seq: number, cardId: string): ProjectEvent =>
      ({
        ...base,
        seq,
        type: "execution_step",
        data: { card_id: cardId, step: 1, status: "running" },
      }) as ProjectEvent;
    const state = run([card(1, "c1", "t"), step(2, "c1"), step(3, "inconnue")]);
    const c = state.items[0];
    expect(c?.kind === "card" && c.card.steps[0]?.status).toBe("running");
    expect(state.items).toHaveLength(1);
    expect(state.lastSeq).toBe(3);
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
