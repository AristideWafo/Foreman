import type { ReactNode } from "react";

/** Retourne l'URL normalisée si (et seulement si) elle est en `http(s)` ; sinon `null`. */
export function safeHttpUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

/**
 * Lien venu de l'API : cliquable seulement en `http(s)` (jamais `javascript:` ni `data:`),
 * sinon le libellé s'affiche comme simple texte.
 */
export function ExternalLink({ href, children }: { href: unknown; children: ReactNode }) {
  const safe = safeHttpUrl(href);
  if (safe === null) return <span>{children}</span>;
  return (
    <a
      href={safe}
      target="_blank"
      rel="noopener noreferrer"
      className="rounded-sm text-foreground underline underline-offset-4 outline-none transition-colors hover:text-muted-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {children}
      <span className="sr-only"> (s'ouvre dans un nouvel onglet)</span>
    </a>
  );
}
