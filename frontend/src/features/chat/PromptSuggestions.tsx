import {
  ChartBarIcon,
  ServerStackIcon,
  ShieldCheckIcon,
  WrenchScrewdriverIcon,
} from "@heroicons/react/24/outline";
import type { ComponentType, SVGProps } from "react";
import { Button } from "@/components/ui/button";

const SUGGESTIONS: { text: string; Icon: ComponentType<SVGProps<SVGSVGElement>> }[] = [
  { text: "Déployer mon application sur un nouveau serveur", Icon: ServerStackIcon },
  { text: "Configurer l'intégration continue d'un dépôt", Icon: WrenchScrewdriverIcon },
  { text: "Auditer la sécurité d'un projet", Icon: ShieldCheckIcon },
  { text: "Mettre en place la supervision d'un service", Icon: ChartBarIcon },
];

/** Exemples de demande : un clic démarre le projet avec ce texte. */
export function PromptSuggestions({
  onPick,
  disabled = false,
}: {
  onPick: (text: string) => void;
  disabled?: boolean;
}) {
  return (
    <section aria-labelledby="suggestions-title" className="flex flex-col gap-3">
      <h3 id="suggestions-title" className="text-xs font-medium uppercase">
        Pour commencer
      </h3>
      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {SUGGESTIONS.map(({ text, Icon }) => (
          <li key={text} className="flex">
            <Button
              type="button"
              variant="outline"
              disabled={disabled}
              onClick={() => onPick(text)}
              className="h-auto min-h-28 w-full flex-col items-start justify-between p-3 text-left whitespace-normal"
            >
              <span>{text}</span>
              <Icon />
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
