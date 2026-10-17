import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// `globals: false` : le nettoyage automatique de Testing Library doit être branché à la main.
afterEach(cleanup);
