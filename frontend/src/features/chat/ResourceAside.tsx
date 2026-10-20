import { useState } from "react";
import { Squares2X2Icon } from "@heroicons/react/24/outline";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import type { ProjectStatus } from "../events/status";
import { ResourcePanel } from "./ResourcePanel";

const KEY = "foreman.resourcePanel";
const PANEL_ID = "resource-panel";
const LABEL = "Ressources et état";

/** Replié par défaut sous `lg` ; le choix de l'utilisateur est mémorisé (la page marche sans `localStorage`). */
function initialOpen(): boolean {
  try {
    const stored = localStorage.getItem(KEY);
    if (stored === "open" || stored === "closed") return stored === "open";
  } catch {
    // Stockage refusé : valeur par défaut.
  }
  return window.matchMedia("(min-width: 1024px)").matches;
}

/**
 * Barre flottante à droite (non modale) ; en mobile, même contenu dans un tiroir.
 * `button` est le bouton d'ouverture, à placer dans l'en-tête.
 */
export function useResourceAside(status: ProjectStatus, connecting: boolean) {
  const mobile = useIsMobile();
  const [desktopOpen, setDesktopOpen] = useState(initialOpen);
  const [sheetOpen, setSheetOpen] = useState(false);
  const open = mobile ? sheetOpen : desktopOpen;

  function toggle() {
    if (mobile) return setSheetOpen(!sheetOpen);
    setDesktopOpen(!desktopOpen);
    try {
      localStorage.setItem(KEY, desktopOpen ? "closed" : "open");
    } catch {
      // Non mémorisé.
    }
  }

  const content = <ResourcePanel status={status} connecting={connecting} />;
  const button = (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      aria-expanded={open}
      aria-controls={PANEL_ID}
      onClick={toggle}
    >
      <Squares2X2Icon />
      <span className="sr-only">{LABEL}</span>
    </Button>
  );
  const aside = mobile ? (
    <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
      <SheetContent side="right" id={PANEL_ID} aria-label={LABEL}>
        <SheetHeader>
          <SheetTitle>{LABEL}</SheetTitle>
          <SheetDescription className="sr-only">Ressources du dernier plan.</SheetDescription>
        </SheetHeader>
        {content}
      </SheetContent>
    </Sheet>
  ) : (
    <aside
      id={PANEL_ID}
      aria-label={LABEL}
      hidden={!desktopOpen}
      className="fixed top-14 right-3 bottom-3 z-10 flex w-80 flex-col rounded-lg bg-sidebar text-sidebar-foreground shadow-sm ring-1 ring-sidebar-border motion-safe:animate-in motion-safe:duration-200 motion-safe:fade-in-0"
    >
      <h2 className="px-4 pt-3 text-sm font-semibold">{LABEL}</h2>
      {content}
    </aside>
  );
  return { button, aside, padded: !mobile && desktopOpen };
}
