import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
