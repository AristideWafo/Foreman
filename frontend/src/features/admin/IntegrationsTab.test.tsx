import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { SidebarProvider } from "@/components/ui/sidebar";
import { AdminPage } from "./AdminPage";

const GITLAB = {
  connector: "gitlab",
  kind: "connector",
  status: "incomplete",
  configured: true,
  tokens: [{ name: "api", scopes: ["api"], boundary: null, configured: true }],
  rights: [],
  last_probe_at: null,
};

/** Faux serveur nommé : un caller du rôle voulu, un connecteur GitLab, test et dépôt du jeton. */
class FakeServer {
  readonly puts: { url: string; body: string }[] = [];
  constructor(private readonly role: "org_admin" | "team_admin") {}

  install() {
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) =>
      Promise.resolve(this.respond(url, init?.method ?? "GET", String(init?.body ?? ""))),
    );
  }

  private respond(url: string, method: string, body: string): Response {
    if (url === "/api/me") {
      const teams = this.role === "team_admin" ? [{ id: "t1", name: "P", role: "team_admin" }] : [];
      return Response.json({ name: "Moi", role: this.role, user_id: "u0", teams });
    }
    if (url === "/api/admin/integrations") return Response.json([GITLAB]);
    if (url === "/api/admin/integrations/gitlab/test") {
      return Response.json({
        connector: "gitlab",
        status: "incomplete",
        rights: [
          { token: "api", right: "read_repository", verdict: "ok" },
          { token: "api", right: "write_repository", verdict: "missing" },
          { token: "api", right: "sudo", verdict: "excess" },
        ],
      });
    }
    if (url === "/api/admin/integrations/gitlab/credentials" && method === "PUT") {
      this.puts.push({ url, body });
      return new Response(null, { status: 204 });
    }
    if (url.startsWith("/api/admin/")) return Response.json([]);
    return Response.json({ error: "not_found" }, { status: 404 });
  }
}

function renderPage() {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SidebarProvider>
          <AdminPage />
        </SidebarProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

afterEach(() => vi.unstubAllGlobals());

test("l'onglet Intégrations n'existe que pour l'org_admin", async () => {
  new FakeServer("team_admin").install();
  renderPage();
  expect(await screen.findByRole("tab", { name: "Invitations" })).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "Intégrations" })).not.toBeInTheDocument();
});

test("le test affiche un verdict par droit", async () => {
  new FakeServer("org_admin").install();
  renderPage();
  await openIntegrations();
  fireEvent.click(await screen.findByRole("button", { name: /Tester/ }));
  expect(await screen.findByText("api : write_repository")).toBeInTheDocument();
  expect(screen.getByText("(manquant)")).toBeInTheDocument();
  expect(screen.getByText("(en trop)")).toBeInTheDocument();
  expect(screen.getByText("(ok)")).toBeInTheDocument();
});

test("le jeton est vidé à l'envoi et ne reste dans aucun cache", async () => {
  const server = new FakeServer("org_admin");
  server.install();
  const client = renderPage();
  await openIntegrations();
  fireEvent.click(await screen.findByRole("button", { name: /Remplacer le jeton/ }));
  const field = screen.getByLabelText("Jeton gitlab");
  expect(field).toHaveAttribute("type", "password");
  expect(field).toHaveAttribute("autocomplete", "new-password");
  fireEvent.change(field, { target: { value: "glpat-SECRET" } });
  fireEvent.click(screen.getByRole("button", { name: "Enregistrer" }));
  await waitFor(() => expect(server.puts).toHaveLength(1));
  expect(server.puts[0]?.url).not.toContain("SECRET");
  expect(server.puts[0]?.body).toContain("glpat-SECRET");
  await waitFor(() => expect(screen.queryByLabelText("Jeton gitlab")).not.toBeInTheDocument());
  const cached = JSON.stringify([
    client
      .getMutationCache()
      .getAll()
      .map((m) => m.state),
    client
      .getQueryCache()
      .getAll()
      .map((q) => q.state.data),
  ]);
  expect(cached).not.toContain("glpat-SECRET");
});

/** Base UI active un onglet au `mousedown`, pas au seul `click`. */
async function openIntegrations() {
  const tab = await screen.findByRole("tab", { name: "Intégrations" });
  fireEvent.mouseDown(tab);
  fireEvent.click(tab);
  await waitFor(() => expect(tab).toHaveAttribute("aria-selected", "true"));
}
