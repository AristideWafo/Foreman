import type { ReactNode } from "react";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";

/** En-tête commun : bouton de barre latérale, séparateur, titre de la page, actions à droite. */
export function PageHeader({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
      <SidebarTrigger />
      <Separator orientation="vertical" className="data-vertical:h-4 data-vertical:self-auto" />
      <h1 className="text-sm font-semibold">{children}</h1>
      {actions ? <div className="ml-auto flex items-center">{actions}</div> : null}
    </header>
  );
}
