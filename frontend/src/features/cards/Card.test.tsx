import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { CardData, ExecutionCardData, PlanCardData } from "../../api/events";
import { applyEvent, initialTimeline, parseEvent, type TimelineState } from "../events/timeline";
import { Card } from "./Card";
// Fixture écrit à la main d'après le contrat additif S1 (docs/plans/semaine-2.md). Le vrai fixture,
// exporté par le scénario `test_s01_nominal` (#31), le remplacera.
import s01 from "./s01-events.json";

const PROJECT_ID = "6f1c2a3e-0000-4000-8000-000000000001";

/** Rejoue les `count` premiers événements du fixture par le parseur puis le reducer, comme le flux SSE. */
function replay(count: number): TimelineState {
  return s01
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
  renderCards(replay(4));
  const plan = screen.getByRole("group", { name: "Plan : Déployer le site statique" });
  expect(within(plan).getByText("Étapes : 0 sur 3 terminées")).toBeInTheDocument();
  expect(within(plan).getByText("Statut du plan :")).toBeInTheDocument();
  expect(within(plan).getByText("Proposé")).toBeInTheDocument();
  // Outil, classe et réversibilité de chaque étape.
  expect(
    within(plan).getByText("provision_server · Écriture (externe) · Compensable"),
  ).toBeVisible();
  expect(within(plan).getByText("http_check · Lecture · Sans objet")).toBeVisible();
  expect(within(plan).getByText("staging")).toBeVisible();
  expect(within(plan).getByText("Niveau 1")).toBeVisible();
  expect(within(plan).getByText("web : nginx, os : debian-12")).toBeVisible();
  expect(within(plan).getByText("static-site (v2)")).toBeVisible();
  expect(within(plan).getByText("site-test")).toBeVisible();
  // Empreinte tronquée, valeur complète en infobulle.
  const hash = within(plan).getByText("sha256:3fa9c1d27be0…");
  expect(hash).toHaveAttribute(
    "title",
    expect.stringMatching(/^sha256:3fa9c1d27be04a56[0-9a-f]{48}$/),
  );
  expect(within(plan).getByRole("button", { name: "Valider le plan" })).toBeEnabled();
});

test("S1, carte exécution réussie : étapes, journal, budget, ressources et résultat", () => {
  renderCards(replay(9));
  const execution = screen.getByRole("group", { name: "Exécution" });
  expect(within(execution).getByRole("status")).toHaveTextContent("Terminée");
  expect(within(execution).getByText(/Vérifier la réponse HTTP/)).toHaveTextContent("Réussie");
  expect(within(execution).getByText("5 sur 20 appels d'outils · 8 s sur 10 min")).toBeVisible();
  expect(within(execution).getByText("Niveau 1")).toBeVisible();
  // Ressource avec URL : lien https ; sans URL : texte seul.
  expect(
    within(execution)
      .getAllByRole("link", { name: /site-test|Ouvrir le site/ })
      .map((a) => a.getAttribute("href")),
  ).toEqual(["https://site-test.example.test/", "https://site-test.example.test/"]);
  expect(within(execution).getByText("journal-interne")).toBeVisible();
  expect(within(execution).queryByRole("link", { name: /journal-interne/ })).toBeNull();
  expect(within(execution).getByText("Le site répond sur le serveur de test.")).toBeVisible();
  // Journal de l'étape 1, reçu à part (execution_log) et conservé quand la carte est réémise.
  expect(within(execution).getByRole("log", { name: "Journal de l'étape 1" })).toHaveTextContent(
    "Création du serveur site-test… Serveur prêt (token=***)",
  );
});

test("après approbation, la carte plan réémise n'a plus de bouton et l'exécution est une seule carte", () => {
  renderCards(replay(9));
  expect(screen.queryByRole("button", { name: "Valider le plan" })).toBeNull();
  expect(screen.getAllByRole("group")).toHaveLength(2);
  expect(screen.getByText("Validé")).toBeInTheDocument();
});

// --- Validation du plan ---------------------------------------------------------------------------

test.each([201, 200])("« Valider le plan » : le statut %i est un succès", async (status) => {
  const fake = new FakeFetch(status, { approval_id: "a", execution_id: "e" });
  stubFetch(fake);
  renderCards(replay(4));
  fireEvent.click(screen.getByRole("button", { name: "Valider le plan" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Plan validé");
  expect(screen.queryByRole("button", { name: "Valider le plan" })).toBeNull();
  expect(fake.calls).toHaveLength(1);
  expect(fake.calls[0]?.url).toBe(
    `/api/projects/${PROJECT_ID}/plans/6f1c2a3e-0000-4000-8000-0000000000a1/approvals`,
  );
  expect(JSON.parse(String(fake.calls[0]?.init?.body))).toEqual({
    plan_hash: "sha256:3fa9c1d27be04a56c8f10e9b7d42a6153fcb8e0a91d4e7625b3c0f18a9d6e742",
    decision: "approved",
  });
});

test("501 non implémenté : erreur propre, sans détail, et on peut réessayer", async () => {
  stubFetch(new FakeFetch(501, { error: "not_implemented" }));
  renderCards(replay(4));
  fireEvent.click(screen.getByRole("button", { name: "Valider le plan" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "La validation n'est pas encore disponible.",
  );
  expect(screen.getByRole("button", { name: "Valider le plan" })).toBeEnabled();
});

test("409 : message clair, bouton bloqué jusqu'à la carte plan réémise", async () => {
  stubFetch(new FakeFetch(409, { error: "plan_hash_mismatch" }));
  renderCards(replay(4));
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
      { name: "piège", provider: "p", resource_type: "t", url: "javascript:alert(1)" },
      { name: "données", provider: "p", resource_type: "t", url: "data:text/html,<b>x</b>" },
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
  const plan = (replay(4).items.find((i) => i.kind === "card")?.card ?? null) as PlanCardData;
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

test("une carte de kind inconnu affiche le repli", () => {
  const unknown = { card_id: "x", kind: "chart" } as unknown as PlanCardData;
  render(<Card card={unknown} projectId={PROJECT_ID} />);
  expect(screen.getByText("Carte non prise en charge.")).toBeInTheDocument();
});
