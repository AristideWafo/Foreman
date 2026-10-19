import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { SidebarProvider } from "@/components/ui/sidebar";
import { AdminPage } from "./AdminPage";

const TEAM = { id: "11111111-1111-4111-8111-111111111111", name: "Plateforme" };
const ADA = {
  id: "22222222-2222-4222-8222-222222222222",
  name: "Ada",
  email: "ada@example.org",
  disabled: false,
  memberships: [{ team_id: TEAM.id, team_name: TEAM.name, role: "team_admin" }],
};

/** Faux serveur nommé : un caller du rôle voulu, une équipe, un utilisateur, aucune invitation. */
class FakeServer {
  readonly posts: string[] = [];
  constructor(private readonly role: "org_admin" | "developer") {}

  install() {
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) =>
      Promise.resolve(this.respond(url, init?.method ?? "GET")),
    );
  }

  private respond(url: string, method: string): Response {
    if (method === "POST") this.posts.push(url);
    if (url === "/api/me") {
      return Response.json({ name: "Moi", role: this.role, user_id: "u0", teams: [] });
    }
    if (url === "/api/admin/teams") return Response.json([TEAM]);
    if (url === "/api/admin/users") return Response.json([ADA]);
    if (url === "/api/admin/invitations" && method === "POST") {
      return Response.json(
        {
          id: "i1",
          email: "x@y.z",
          role: "developer",
          team_id: null,
          expires_at: "2030-01-01T00:00:00Z",
          link: "https://app/accept-invite#token=SECRET",
        },
        { status: 201 },
      );
    }
    if (url === "/api/admin/invitations") return Response.json([]);
    return Response.json({ error: "not_found" }, { status: 404 });
  }
}

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <SidebarProvider>
          <AdminPage />
        </SidebarProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("un org_admin voit équipes, membres et le lien d'invitation une seule fois", async () => {
  new FakeServer("org_admin").install();
  renderPage();
  expect(await screen.findByRole("tab", { name: "Équipes" })).toBeInTheDocument();
  expect(await screen.findByRole("cell", { name: "Plateforme" })).toBeInTheDocument();
  expect(screen.getByLabelText("Premier administrateur")).toBeRequired();

  fireEvent.click(screen.getByRole("tab", { name: "Membres" }));
  expect(await screen.findByLabelText("Rôle de Ada dans Plateforme")).toHaveValue("team_admin");

  fireEvent.click(screen.getByRole("tab", { name: "Invitations" }));
  fireEvent.change(screen.getByLabelText("Adresse e-mail"), { target: { value: "x@y.z" } });
  fireEvent.click(screen.getByRole("button", { name: "Inviter" }));
  expect(await screen.findByLabelText("Lien d'invitation")).toHaveValue(
    "https://app/accept-invite#token=SECRET",
  );
  expect(screen.getByRole("button", { name: "Copier" })).toBeInTheDocument();
  expect(screen.getByText(/ne sera plus jamais affiché/)).toBeInTheDocument();
});

test("un developer voit un message neutre, sans appel d'administration", async () => {
  new FakeServer("developer").install();
  renderPage();
  expect(
    await screen.findByText("Cette page est réservée aux administrateurs."),
  ).toBeInTheDocument();
  expect(screen.queryByRole("tab")).not.toBeInTheDocument();
});
