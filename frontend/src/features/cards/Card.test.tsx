import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { PlanCardData, ProjectEvent } from "../../api/events";
import { Card } from "./Card";

// Événement d'exemple conforme au contrat v1 (enveloppe `Event`, type `card`).
const event: Extract<ProjectEvent, { type: "card" }> = {
  v: 1,
  seq: 3,
  project_id: "6f1c2a3e-0000-4000-8000-000000000001",
  turn_id: "6f1c2a3e-0000-4000-8000-000000000002",
  at: "2026-10-17T10:00:00Z",
  type: "card",
  data: {
    card_id: "plan-1",
    kind: "plan",
    title: "Déployer l'application",
    summary: "Trois étapes pour la mise en ligne.",
    steps: [
      { step: 1, title: "Préparer le serveur", status: "succeeded" },
      { step: 2, title: "Copier les fichiers", status: "running" },
      { step: 3, title: "Redémarrer le service", status: "pending" },
    ],
  },
};

test("la carte plan affiche titre, résumé et étapes avec leur statut", () => {
  render(<Card card={event.data} />);
  expect(screen.getByRole("heading", { name: "Déployer l'application" })).toBeInTheDocument();
  expect(screen.getByText("Trois étapes pour la mise en ligne.")).toBeInTheDocument();
  const steps = screen.getAllByRole("listitem");
  expect(steps).toHaveLength(3);
  // `step` est un indice qui commence à 1 (contrat v1) : on l'affiche tel quel.
  expect(steps.map((s) => s.textContent?.match(/^\d+/)?.[0])).toEqual(["1", "2", "3"]);
  expect(steps[0]).toHaveTextContent("Préparer le serveur");
  expect(steps[0]).toHaveTextContent("Réussie");
  expect(steps[1]).toHaveTextContent("En cours");
  expect(steps[2]).toHaveTextContent("En attente");
});

test("une carte de kind inconnu affiche le repli", () => {
  const unknown = { card_id: "x", kind: "chart" } as unknown as PlanCardData;
  render(<Card card={unknown} />);
  expect(screen.getByText("Carte non prise en charge.")).toBeInTheDocument();
});

test("un texte contenant du HTML est affiché littéralement", () => {
  const html = '<img src=x onerror="alert(1)"> <b>gras</b>';
  const card: PlanCardData = { ...event.data, title: html, summary: html };
  const { container } = render(<Card card={card} />);
  expect(screen.getByRole("heading")).toHaveTextContent(html);
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("b")).toBeNull();
});
