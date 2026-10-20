import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
import { App } from "./App";

test("l'accueil affiche le titre et le champ de demande", () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.getByRole("heading", { name: "Que voulez-vous faire ?" })).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Votre demande" })).toBeInTheDocument();
});

function renderAt(path: string) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("/login affiche le formulaire de connexion", () => {
  renderAt("/login");
  expect(screen.getByLabelText("Adresse e-mail")).toHaveAttribute("autocomplete", "username");
  expect(screen.getByLabelText("Mot de passe")).toHaveAttribute("autocomplete", "current-password");
});

test("une réponse 401 redirige vers /login", async () => {
  vi.stubGlobal("fetch", () =>
    Promise.resolve(Response.json({ error: "unauthenticated" }, { status: 401 })),
  );
  renderAt("/");
  expect(await screen.findByRole("heading", { name: "Connexion à Foreman" })).toBeInTheDocument();
  vi.unstubAllGlobals();
});
