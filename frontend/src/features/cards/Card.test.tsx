import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { CardData, ExecutionCardData, PlanCardData } from "../../api/events";
import {
  applyEvent,
  foldExecutions,
  initialTimeline,
  parseEvent,
  type TimelineState,
} from "../events/timeline";
import { findRetry } from "../chat/ProjectPage";
import { Card } from "./Card";
// Fixture réel : exporté par `make s01-fixture` depuis le scénario `test_s01_nominal` (#31).
import s01 from "./s01-events.json";
// Fixture réel : exporté par `make s02-fixture` depuis le scénario S2 (#34).
import s02 from "./s02-events.json";
// Fixture réel : exporté par `make s10-fixture` depuis le scénario S10 (#39).
import s10 from "./s10-events.json";
// Fixture réel : exporté par `make s11-fixture` depuis le scénario S11 (#42).
import s11 from "./s11-events.json";

// Fixture réel : exporté par `make s12-fixture` depuis le scénario S12 (#44).
import s12 from "./s12-events.json";

const PROJECT_ID = "00000000-0000-4000-8000-000000000001";
const PLAN_ID = "00000000-0000-4000-8000-000000000003";
const PLAN_HASH = `sha256:${"0".repeat(63)}1`;
const PLAN_SEQ = 4; // première carte plan (proposée)
const LAST_SEQ = 40; // carte d'exécution terminée

/** Rejoue les `count` premiers événements du fixture par le parseur puis le reducer, comme le flux SSE. */
function replay(count: number, events: readonly unknown[] = s01): TimelineState {
  return events
    .slice(0, count)
    .map((raw) => parseEvent(JSON.stringify(raw)))
    .reduce((state, event) => (event ? applyEvent(state, event) : state), initialTimeline);
}

function renderCards(state: TimelineState) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      {state.items.map((item) =>
        item.kind === "card" ? (
          <Card key={item.key} card={item.card} projectId={PROJECT_ID} logs={item.logs} />
        ) : null,
      )}
    </QueryClientProvider>,
  );
}

/** Faux `fetch` nommé : enregistre les appels et répond avec le statut voulu. */
class FakeFetch {
  readonly calls: { url: string; init: RequestInit | undefined }[] = [];
  constructor(
    private readonly status: number,
    private readonly body: unknown,
  ) {}
  readonly fetch = (url: string, init?: RequestInit): Promise<Response> => {
    this.calls.push({ url, init });
    return Promise.resolve(new Response(JSON.stringify(this.body), { status: this.status }));
  };
}

function stubFetch(fake: FakeFetch) {
  vi.stubGlobal("fetch", fake.fetch);
}

afterEach(() => {
  vi.unstubAllGlobals();
});

// --- Critère de fin : S1 rendu depuis les événements ---------------------------------------------

test("S1, carte plan : étapes, Skills, empreinte et bouton « Valider le plan »", () => {
  renderCards(replay(PLAN_SEQ));
  const plan = screen.getByRole("group", {
    name: "Plan : Safe Eat : GitLab et déploiement en staging",
  });
  expect(within(plan).getByText("Étapes : 0 sur 8 terminées")).toBeInTheDocument();
  expect(within(plan).getByText("Proposé")).toBeInTheDocument();
  // Outil, classe et réversibilité de chaque étape.
  expect(
    within(plan).getAllByText("gitlab.create_group · Écriture (registre) · Compensable"),
  ).toHaveLength(3);
  expect(within(plan).getByText("server.healthcheck · Lecture · Sans objet")).toBeVisible();
  expect(within(plan).getByText("staging")).toBeVisible();
  expect(within(plan).getByText("Niveau 2")).toBeVisible();
  expect(within(plan).getByText("backend : go-api, frontend : vue-web")).toBeVisible();
  expect(
    within(plan).getByText(
      "gitlab-project-creation (v1), go-backend-standard (v1), docker-staging-deploy (v1)",
    ),
  ).toBeVisible();
  // Empreinte tronquée, valeur complète en infobulle.
  expect(within(plan).getByText("sha256:000000000000…")).toHaveAttribute("title", PLAN_HASH);
  expect(within(plan).getByRole("button", { name: "Valider le plan" })).toBeEnabled();
});

test("S1, carte exécution réussie : étapes, journal, budget, ressources et résultat", () => {
  renderCards(replay(LAST_SEQ));
  const execution = screen.getByRole("group", { name: "Exécution" });
  expect(within(execution).getByRole("status")).toHaveTextContent("Terminée");
  expect(within(execution).getByText(/Vérifier la santé du projet/)).toHaveTextContent("Réussie");
  expect(within(execution).getByText("8 sur 60 appels d'outils · 0 s sur 30 min")).toBeVisible();
  expect(within(execution).getByText("Niveau 2")).toBeVisible();
  // Ressources avec URL : lien https ; sans URL : texte seul. Puis les liens du résultat.
  const hrefs = within(execution)
    .getAllByRole("link")
    .map((a) => a.getAttribute("href"));
  expect(hrefs).toHaveLength(10);
  expect(hrefs[0]).toBe("https://gitlab.example.org/foreman-demo/safe-eat");
  expect(within(execution).getByText("staging/safe-eat")).toBeVisible();
  expect(within(execution).queryByRole("link", { name: "staging/safe-eat" })).toBeNull();
  expect(within(execution).getByText("8 étapes réussies sur 8 en staging.")).toBeVisible();
  // Journal de l'étape 1, reçu à part (execution_log) et conservé quand la carte est réémise.
  expect(within(execution).getByRole("log", { name: "Journal de l'étape 1" })).toHaveTextContent(
    "groupe foreman-demo/safe-eat créé",
  );
});

test("après approbation, la carte plan réémise n'a plus de bouton et l'exécution est une seule carte", () => {
  renderCards(replay(LAST_SEQ));
  expect(screen.queryByRole("button", { name: "Valider le plan" })).toBeNull();
  expect(screen.getAllByRole("group")).toHaveLength(2);
  expect(screen.getByText("Validé")).toBeInTheDocument();
});

// --- Validation du plan ---------------------------------------------------------------------------

test.each([201, 200])("« Valider le plan » : le statut %i est un succès", async (status) => {
  const fake = new FakeFetch(status, { approval_id: "a", execution_id: "e" });
  stubFetch(fake);
  renderCards(replay(PLAN_SEQ));
  fireEvent.click(screen.getByRole("button", { name: "Valider le plan" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Plan validé");
  expect(screen.queryByRole("button", { name: "Valider le plan" })).toBeNull();
  const posts = fake.calls.filter((call) => call.init?.method === "POST"); // hors /api/me
  expect(posts).toHaveLength(1);
  expect(posts[0]?.url).toBe(`/api/projects/${PROJECT_ID}/plans/${PLAN_ID}/approvals`);
  expect(JSON.parse(String(posts[0]?.init?.body))).toEqual({
    plan_hash: PLAN_HASH,
    decision: "approved",
  });
});

test("erreur serveur : message générique sans détail, et on peut réessayer", async () => {
  stubFetch(new FakeFetch(500, { error: "internal_error" }));
  renderCards(replay(PLAN_SEQ));
  fireEvent.click(screen.getByRole("button", { name: "Valider le plan" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "La validation a échoué. Réessayez dans un instant.",
  );
  expect(screen.getByRole("button", { name: "Valider le plan" })).toBeEnabled();
});

test("409 : message clair, bouton bloqué jusqu'à la carte plan réémise", async () => {
  stubFetch(new FakeFetch(409, { error: "plan_hash_mismatch" }));
  renderCards(replay(PLAN_SEQ));
  fireEvent.click(screen.getByRole("button", { name: "Valider le plan" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("a changé"));
  expect(screen.getByRole("button", { name: "Valider le plan" })).toBeDisabled();
});

// --- Sécurité des textes et des liens --------------------------------------------------------------

test("texte de l'API affiché comme texte ; liens non http(s) jamais cliquables", () => {
  const html = '<img src=x onerror="alert(1)"> <b>gras</b>';
  const execution: ExecutionCardData = {
    card_id: "x",
    kind: "execution",
    execution_id: "e",
    plan_card_id: "p",
    state: "blocked",
    autonomy_level: 1,
    steps: [
      { step: 1, title: html, status: "failed", tool: null, tool_class: null, reversibility: null },
    ],
    budget: { tool_calls_used: 0, tool_calls_max: 1, elapsed_s: 0, max_minutes: 1 },
    resources: [
      {
        name: "piège",
        provider: "p",
        resource_type: "t",
        reused: null,
        url: "javascript:alert(1)",
      },
      {
        name: "données",
        provider: "p",
        resource_type: "t",
        reused: null,
        url: "data:text/html,<b>x</b>",
      },
    ],
    result: { summary: html, links: [{ label: "lien", url: "javascript:alert(2)" }] },
  };
  const { container } = render(
    <Card card={execution} projectId={PROJECT_ID} logs={{ 1: [html] }} />,
  );
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("b")).toBeNull();
  expect(screen.queryAllByRole("link")).toHaveLength(0);
  expect(screen.getByText("piège")).toBeVisible();
  expect(screen.getByRole("log")).toHaveTextContent(html);
});

test("plan dont le statut n'est pas « proposed » ou non approuvable : pas de bouton", () => {
  const plan = (replay(PLAN_SEQ).items.find((i) => i.kind === "card")?.card ??
    null) as PlanCardData;
  for (const card of [
    { ...plan, approvable: false },
    { ...plan, status: "expired" as const },
  ]) {
    const { unmount } = render(
      <QueryClientProvider client={new QueryClient()}>
        <Card card={card satisfies CardData} projectId={PROJECT_ID} />
      </QueryClientProvider>,
    );
    expect(screen.queryByRole("button", { name: "Valider le plan" })).toBeNull();
    unmount();
  }
});

// --- Critère de fin : S2, carte de clarification rendue depuis l'événement `clarification` ----------

test("S2, carte de clarification : question, option imposée, boutons Répondre et Reporter", () => {
  renderCards(replay(4, s02)); // seq 4 : première carte de clarification (question ouverte)
  const card = screen.getByRole("group", { name: "Clarification" });
  const options = within(card).getByRole("group", {
    name: "Sur quel environnement faut-il déployer Safe Eat ?",
  });
  expect(within(options).getByRole("button", { name: "staging" })).toBeVisible();
  expect(within(card).getByRole("button", { name: "Répondre" })).toBeDisabled();
  expect(within(card).getByRole("button", { name: "Reporter" })).toBeEnabled();
});

test("une carte de kind inconnu affiche le repli", () => {
  const unknown = { card_id: "x", kind: "chart" } as unknown as PlanCardData;
  render(<Card card={unknown} projectId={PROJECT_ID} />);
  expect(screen.getByText("Carte non prise en charge.")).toBeInTheDocument();
});

// --- Critère de fin : S10, carte d'approbation rendue selon le rôle de /api/me ----------------------------

/** Faux `fetch` : `/api/me` répond avec le rôle voulu. */
function stubMe(role: "developer" | "team_admin") {
  const fake = new FakeFetch(200, { name: "x", role, user_id: "u" });
  stubFetch(fake);
  return fake;
}

test("S10, développeur : carte d'approbation sans bouton « Approuver », en attente d'un administrateur", async () => {
  const fake = stubMe("developer");
  renderCards(replay(7, s10)); // seq 7 : demande en attente
  const card = screen.getByRole("group", { name: "Approbation administrateur" });
  expect(within(card).getByText("production")).toBeVisible();
  expect(within(card).getByText("R7-ecriture-production")).toBeVisible();
  await waitFor(() => expect(fake.calls).toHaveLength(1)); // /api/me a répondu : toujours aucun bouton
  expect(within(card).getByRole("status")).toHaveTextContent("En attente d'un administrateur");
  expect(within(card).queryByRole("button")).toBeNull();
});

test("S10, team_admin : boutons « Approuver » et « Refuser » ; approuvée, plus de bouton", async () => {
  stubMe("team_admin");
  const { unmount } = renderCards(replay(7, s10));
  expect(await screen.findByRole("button", { name: "Approuver" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Refuser" })).toBeEnabled();
  unmount();
  renderCards(replay(8, s10)); // seq 8 : approuvée par admin
  expect(screen.getByRole("status")).toHaveTextContent("Approuvée par admin");
  expect(screen.queryByRole("button", { name: "Approuver" })).toBeNull();
});

// --- Critère de fin : S11, la carte d'exécution marque les ressources déjà présentes ------------------------

test("S11, rejeu : 6 badges « déjà présente » et 8 étapes réussies sur la dernière carte d'exécution", () => {
  renderCards(replay(78, s11)); // seq 78 : seconde exécution, terminée
  const card = screen.getAllByRole("group", { name: "Exécution" }).at(-1)!;
  expect(within(card).getAllByText("déjà présente")).toHaveLength(6);
  // Résumé fourni par le serveur, affiché tel quel.
  expect(
    within(card).getByText(
      "8 étapes réussies sur 8 en staging. 6 ressources déjà présentes, aucune créée.",
    ),
  ).toBeVisible();
});

// --- Relancer un plan bloqué ----------------------------------------------------------------------

test("exécution bloquée : bouton « Relancer le plan » ; exécution réussie : aucun", () => {
  const done = replay(LAST_SEQ).items.find((i) => i.kind === "card" && i.card.kind === "execution");
  const card = done?.kind === "card" ? (done.card as ExecutionCardData) : null;
  expect(card?.state).toBe("succeeded");
  const view = (state: ExecutionCardData["state"]) =>
    render(
      <QueryClientProvider client={new QueryClient()}>
        <Card card={{ ...card!, state }} projectId={PROJECT_ID} retryText="Déploie Safe Eat" />
      </QueryClientProvider>,
    );
  const ok = view("succeeded");
  expect(screen.queryByRole("button", { name: "Relancer le plan" })).toBeNull();
  ok.unmount();
  view("blocked");
  expect(screen.getByRole("button", { name: "Relancer le plan" })).toBeEnabled();
});

// --- Critère de fin : S12, plan invalidé ---------------------------------------------------------

test("S12, plan v1 invalidé : raison, changements, sans « Valider le plan » ; « Refaire le plan » seulement si non remplacé", () => {
  const state = replay(46, s12); // seq 46 : plan v1 invalidé (project_changed), plan v2 déjà exécuté
  const items = foldExecutions(state.items);
  const plan = items.find((i) => i.kind === "card" && i.card.kind === "plan" && !i.execution);
  if (plan?.kind !== "card") throw new Error("plan v1 absent");
  // Plan v2 plus récent : findRetry ne propose rien pour v1.
  expect(findRetry(items)).toBeNull();
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <Card card={plan.card} projectId={PROJECT_ID} logs={plan.logs} retryText="Crée le projet" />
    </QueryClientProvider>,
  );
  const group = screen.getByRole("group", { name: /^Plan :/ });
  expect(within(group).getByText("Invalidé")).toBeVisible();
  expect(within(group).getByText("Le projet a changé depuis ce plan")).toBeVisible();
  expect(within(group).getByText("Registre : gitlab_group")).toBeVisible();
  expect(within(group).queryByRole("button", { name: "Valider le plan" })).toBeNull();
  expect(within(group).getByRole("button", { name: "Refaire le plan" })).toBeEnabled();
});

test("S12, plan invalidé le plus récent : findRetry renvoie le message d'origine", () => {
  const events = [...s12.slice(0, 4), { ...s12[45], seq: 5 }]; // seq contigus // message, plan v1 proposé, puis sa réémission invalidée
  expect(findRetry(foldExecutions(replay(5, events).items))).toMatchObject({
    text: "Crée le projet Safe Eat : GitLab, puis déploiement en staging.",
  });
});
