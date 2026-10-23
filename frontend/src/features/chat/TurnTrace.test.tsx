import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { TurnTrace } from "./TurnTrace";

test("la trace affiche la lecture en français et signale l'échec", () => {
  render(
    <TurnTrace
      status="running"
      tools={["gitlab.list_groups", "gitlab.read_file"]}
      failed={["gitlab.read_file"]}
    />,
  );
  expect(screen.getByText("Lecture des groupes")).toBeTruthy();
  expect(screen.getByText("Lecture d'un fichier : échec")).toBeTruthy();
});
