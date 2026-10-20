import { expect, test } from "vitest";
import type { ExecutionCardData, PlanCardData, ResourceRef } from "../../api/events";
import s12 from "../cards/s12-events.json";
import { projectStatus, type ResourceStatus } from "./status";
import { applyEvent, foldExecutions, initialTimeline, parseEvent } from "./timeline";
import type { TimelineItem } from "./timeline";

const step = (n: number, status: PlanCardData["steps"][number]["status"]) => ({
  step: n,
  title: `Étape ${n}`,
  status,
  tool: null,
  tool_class: null,
  reversibility: null,
});

const ref = (
  r: Partial<ResourceRef> & Pick<ResourceRef, "provider" | "resource_type" | "name">,
): ResourceRef => ({
  reused: null,
  step: null,
  url: null,
  ...r,
});

const PLAN = {
  kind: "plan",
  card_id: "plan-1",
  title: "Plan test",
  status: "dev_approved",
  environment: "staging",
  steps: [step(1, "pending"), step(2, "pending")],
  expected_resources: [
    { provider: "gitlab", resource_type: "gitlab_project", name: "api", step: 1 },
    { provider: "server", resource_type: "server_project", name: "api", step: 2 },
  ],
} as unknown as PlanCardData;

/** Plan seul, ou plan replié avec son exécution, comme `foldExecutions` les fournit à l'écran. */
function items(execution?: Partial<ExecutionCardData>): TimelineItem[] {
  const base = [{ key: "p", kind: "card", card: PLAN, logs: {} }] as TimelineItem[];
  if (!execution) return base;
  const card = {
    kind: "execution",
    card_id: "exec-1",
    plan_card_id: "plan-1",
    state: "running",
    resources: [],
    ...execution,
  } as unknown as ExecutionCardData;
  return foldExecutions([...base, { key: "x", kind: "card", card, logs: { 1: ["a", "b"] } }]);
}

const statuses = (list: TimelineItem[]): ResourceStatus[] =>
  projectStatus(list).resources.map((r) => r.status);

test("sans plan : état vide", () => {
  expect(projectStatus([]).summary).toBeNull();
});

test("ciblées, puis en cours, puis créée et réutilisée", () => {
  expect(statuses(items())).toEqual(["targeted", "targeted"]);
  expect(statuses(items({ steps: [step(1, "running"), step(2, "pending")] }))).toEqual([
    "running",
    "targeted",
  ]);
  const done = items({
    state: "succeeded",
    steps: [step(1, "succeeded"), step(2, "succeeded")],
    resources: [
      ref({
        provider: "gitlab",
        resource_type: "gitlab_project",
        name: "5000",
        step: 1,
        url: "https://x/5000",
      }),
      ref({
        provider: "server",
        resource_type: "server_project",
        name: "api",
        step: 2,
        reused: true,
      }),
    ],
  });
  const view = projectStatus(done);
  expect(view.resources.map((r) => r.status)).toEqual(["created", "reused"]);
  expect(view.resources[0]?.url).toBe("https://x/5000");
  expect(view.summary?.counts).toMatchObject({ created: 1, reused: 1, targeted: 0 });
  expect(view.summary?.lastAction).toBe("b");
});

test("échec et annulation par étape", () => {
  expect(
    statuses(items({ state: "blocked", steps: [step(1, "failed"), step(2, "pending")] })),
  ).toEqual(["failed", "targeted"]);
  expect(
    statuses(
      items({ state: "failed_compensated", steps: [step(1, "compensated"), step(2, "failed")] }),
    ),
  ).toEqual(["cancelled", "failed"]);
});

test("ressource de l'exécution sans équivalent ciblé : ajoutée telle quelle", () => {
  const list = items({
    state: "succeeded",
    steps: [step(1, "succeeded"), step(2, "succeeded"), step(3, "succeeded")],
    resources: [ref({ provider: "dns", resource_type: "dns_record", name: "a.example", step: 3 })],
  });
  expect(statuses(list)).toEqual(["created", "created", "created"]);
});

test("scénario S12 rejoué : des ressources réutilisées apparaissent", () => {
  const state = s12.reduce((acc, raw) => {
    const event = parseEvent(JSON.stringify(raw));
    return event ? applyEvent(acc, event) : acc;
  }, initialTimeline);
  const view = projectStatus(foldExecutions(state.items));
  expect(view.resources.length).toBeGreaterThan(0);
  expect(view.summary?.counts.reused).toBeGreaterThan(0);
});
