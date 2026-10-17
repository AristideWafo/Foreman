import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import { App } from "./App";

test("l'accueil affiche le titre et le champ de demande", () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.getByRole("heading", { name: "Foreman" })).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Votre demande" })).toBeInTheDocument();
});
