import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { PageHeader } from "@/components/PageHeader";
import { SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { applyEvent, initialTimeline, participants } from "../events/timeline";
import { Participants } from "./Participants";
import { sameAuthorAsPrevious, TimelineEntry } from "./ProjectPage";

const ALICE = { id: "00000000-0000-4000-8000-00000000d001", name: "Alice Martin" };
const BOB = { id: "00000000-0000-4000-8000-00000000d002", name: "Bob" };

/** Flux nommé : trois messages utilisateur de deux auteurs, Alice écrivant deux fois de suite. */
function twoAuthors() {
  return [ALICE, ALICE, BOB].reduce(
    (state, author, i) =>
      applyEvent(state, {
        v: 1,
        at: "2026-01-01T00:00:00Z",
        project_id: "p",
        turn_id: "t",
        seq: i + 1,
        type: "message",
        data: { role: "user", text: `message ${i + 1}`, author },
      }),
    initialTimeline,
  ).items;
}

test("deux auteurs : un nom par groupe au-dessus des messages, deux avatars dans l'en-tête", () => {
  const items = twoAuthors();
  render(
    <SidebarProvider>
      <TooltipProvider>
        <PageHeader actions={<Participants authors={participants(items)} />}>Projet</PageHeader>
        {items.map((item, i) => (
          <TimelineEntry
            key={item.key}
            item={item}
            projectId="p"
            showAuthor={!sameAuthorAsPrevious(items[i - 1], item)}
          />
        ))}
      </TooltipProvider>
    </SidebarProvider>,
  );
  expect(screen.getAllByText("Alice Martin")).toHaveLength(1);
  expect(screen.getAllByText("Bob")).toHaveLength(1);
  const avatars = screen.getAllByRole("img");
  expect(avatars.map((a) => a.getAttribute("aria-label"))).toEqual(["Alice Martin", "Bob"]);
  // Pastille décorative à droite de la bulle : une par suite (AM, B), la 2e d'Alice garde la place.
  const slots = document.querySelectorAll('[data-slot="message-avatar"]');
  expect([...slots].map((s) => s.textContent)).toEqual(["AM", "", "B"]);
  expect(document.querySelector('[data-slot="message"] > :first-child')).toBe(slots[0]);
});
