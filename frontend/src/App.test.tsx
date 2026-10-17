import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { App } from "./App";

test("affiche le titre", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "Foreman" })).toBeInTheDocument();
});
