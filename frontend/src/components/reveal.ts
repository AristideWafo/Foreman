import type { CSSProperties } from "react";

/** Apparition douce, décalée par rang : à poser sur le `className` et le `style` d'un élément. */
export function reveal(index: number, stepMs = 150): { className: string; style: CSSProperties } {
  return {
    className:
      "motion-safe:animate-in motion-safe:duration-200 motion-safe:fade-in-0 motion-safe:slide-in-from-left-1 motion-safe:fill-mode-backwards",
    style: { animationDelay: `${index * stepMs}ms` },
  };
}
