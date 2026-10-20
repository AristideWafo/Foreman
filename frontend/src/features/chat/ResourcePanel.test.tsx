import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { ProjectStatus, ResourceView } from "../events/status";
import { ResourcePanel } from "./ResourcePanel";

const EMPTY_COUNTS = { targeted: 0, running: 0, created: 0, reused: 0, failed: 0, cancelled: 0 };

function status(resources: ResourceView[]): ProjectStatus {
  const counts = { ...EMPTY_COUNTS };
  for (const r of resources) counts[r.status]++;
  return {
    plan: null,
    resources,
    summary: {
      environment: "staging",
      title: "Plan test",
      planStatus: "dev_approved",
      executionState: "running",
      currentStep: "Créer le dépôt",
      counts,
      lastAction: null,
    },
  };
}

test("chaque ressource porte son statut en texte accessible, le résumé est un statut", () => {
  render(
    <ResourcePanel
      connecting={false}
      status={status([
        { provider: "gitlab", resource_type: "gitlab_project", name: "api", status: "created" },
        { provider: "server", resource_type: "server_project", name: "api", status: "targeted" },
        { provider: "dns", resource_type: "dns_record", name: "a.example", status: "failed" },
      ])}
    />,
  );
  expect(screen.getByRole("status")).toHaveTextContent("Plan test");
  expect(screen.getByText("Créée")).toBeInTheDocument();
  expect(screen.getByText("Ciblée")).toBeInTheDocument();
  expect(screen.getByText("En échec")).toBeInTheDocument();
});

test("états vides et connexion", () => {
  const none = { plan: null, resources: [], summary: null };
  const { rerender } = render(<ResourcePanel connecting={false} status={none} />);
  expect(screen.getByText(/Aucun plan pour l'instant/)).toBeInTheDocument();
  rerender(<ResourcePanel connecting={false} status={status([])} />);
  expect(screen.getByText("Ce plan ne crée aucune ressource.")).toBeInTheDocument();
  rerender(<ResourcePanel connecting={true} status={none} />);
  expect(screen.getByLabelText("Chargement des ressources")).toBeInTheDocument();
});
