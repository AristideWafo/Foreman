import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// `globals: false` : le nettoyage automatique de Testing Library doit être branché à la main.
afterEach(cleanup);

// jsdom n'a pas matchMedia ni ResizeObserver, que la barre latérale et le défilement de la conversation utilisent.
window.matchMedia ??= (query: string) =>
  ({
    matches: false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }) as unknown as MediaQueryList;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
