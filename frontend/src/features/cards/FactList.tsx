import type { ReactNode } from "react";

export interface Fact {
  label: string;
  value: ReactNode | null | undefined;
}

/** Liste de définitions (étiquette `text-xs`, valeur `text-sm`) ; les valeurs absentes ne s'affichent pas. */
export function FactList({ facts }: { facts: readonly Fact[] }) {
  const shown = facts.filter((f) => f.value !== null && f.value !== undefined && f.value !== "");
  if (shown.length === 0) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
      {shown.map((fact) => (
        <div key={fact.label} className="col-span-2 grid grid-cols-subgrid items-baseline">
          <dt className="text-xs text-muted-foreground">{fact.label}</dt>
          <dd className="min-w-0 wrap-break-word">{fact.value}</dd>
        </div>
      ))}
    </dl>
  );
}
