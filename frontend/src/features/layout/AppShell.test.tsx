import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, test, vi } from "vitest";
import { AppShell } from "./AppShell";

/** Faux serveur nommé : `/healthz` annonce la persistance voulue, la liste des projets est vide. */
function stubServer(persistence: string) {
  const respond = (url: string) =>
    Response.json(url === "/healthz" ? { persistence } : [], { status: 200 });
  vi.stubGlobal("fetch", (url: string) => Promise.resolve(respond(url)));
}

function renderShell() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("le badge Mode mémoire s'affiche pour memory", async () => {
  stubServer("memory");
  renderShell();
  expect(await screen.findByRole("status")).toHaveTextContent("Mode mémoire");
});

test("aucun badge pour postgres", async () => {
  stubServer("postgres");
  renderShell();
  await screen.findByText("Aucun projet pour l'instant.");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

test("le nom et le rôle de l'utilisateur s'affichent", async () => {
  vi.stubGlobal("fetch", (url: string) =>
    Promise.resolve(
      Response.json(
        url === "/api/me"
          ? { name: "Ada", role: "team_admin", user_id: "u1" }
          : url === "/healthz"
            ? { persistence: "postgres" }
            : [],
      ),
    ),
  );
  renderShell();
  expect(await screen.findByText("Admin d'équipe")).toBeInTheDocument();
  expect(screen.getByText("Ada")).toBeInTheDocument();
});

/** Faux serveur nommé : deux équipes partagées et un projet personnel. */
function stubTeamsServer() {
  const project = (id: string, title: string, team_id: string, team_name: string) => ({
    id,
    title,
    team_id,
    team_name,
    created_at: "2026-01-01T00:00:00Z",
  });
  const teams = [
    { id: "t1", name: "Alpha", role: "member" },
    { id: "t2", name: "Beta", role: "member" },
  ];
  vi.stubGlobal("fetch", (url: string) =>
    Promise.resolve(
      Response.json(
        url === "/api/me"
          ? { name: "Ada", role: "member", user_id: "u1", teams }
          : url === "/healthz"
            ? { persistence: "postgres" }
            : [
                project("p1", "Projet A", "t1", "Alpha"),
                project("p2", "Projet B", "t2", "Beta"),
                project("p3", "Projet perso", "t0", "Ada"),
              ],
      ),
    ),
  );
}

test("les projets se filtrent par sélection multiple d'équipes, mémorisée", async () => {
  localStorage.clear();
  stubTeamsServer();
  renderShell();
  expect(await screen.findByText("Projet perso")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Toutes" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Alpha" }));
  fireEvent.click(screen.getByRole("button", { name: "Personnel" }));
  expect(screen.getByRole("button", { name: "Alpha" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("Projet A")).toBeInTheDocument();
  expect(screen.getByText("Projet perso")).toBeInTheDocument();
  expect(screen.queryByText("Projet B")).not.toBeInTheDocument();
  expect(localStorage.getItem("foreman.activeTeams")).toBe('["t1","personal"]');
});
