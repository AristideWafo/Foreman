import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Author } from "../events/timeline";

const MAX_SHOWN = 4;
/** Nuances neutres du thème (jetons `chart`) ; le choix dépend seulement de l'id, donc stable. */
const SHADES = ["bg-chart-2", "bg-chart-3", "bg-chart-4", "bg-chart-5"];

function shadeOf(id: string): string {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return SHADES[hash % SHADES.length] ?? "bg-chart-3";
}

function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const first = words[0]?.[0] ?? "";
  const last = words.length > 1 ? (words[words.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase() || "?";
}

const PILL =
  "flex size-6 items-center justify-center rounded-full text-[0.625rem] font-medium ring-2 ring-background outline-none focus-visible:ring-ring";

/** Pastilles des personnes intervenues dans le chat ; le nom apparaît au survol et au focus. */
export function Participants({ authors }: { authors: readonly Author[] }) {
  if (authors.length === 0) return null;
  const shown = authors.slice(0, MAX_SHOWN);
  const hidden = authors.slice(MAX_SHOWN).map((a) => a.name);
  return (
    <ul aria-label="Participants" className="flex -space-x-1.5">
      {shown.map((author) => (
        <li key={author.id}>
          <Tooltip>
            <TooltipTrigger
              render={
                <span
                  role="img"
                  tabIndex={0}
                  aria-label={author.name}
                  className={`${PILL} ${shadeOf(author.id)} text-white`}
                />
              }
            >
              {initials(author.name)}
            </TooltipTrigger>
            <TooltipContent>{author.name}</TooltipContent>
          </Tooltip>
        </li>
      ))}
      {hidden.length > 0 ? (
        <li>
          <Tooltip>
            <TooltipTrigger
              render={
                <span
                  role="img"
                  tabIndex={0}
                  aria-label={hidden.join(", ")}
                  className={`${PILL} bg-muted text-muted-foreground`}
                />
              }
            >
              +{hidden.length}
            </TooltipTrigger>
            <TooltipContent>{hidden.join(", ")}</TooltipContent>
          </Tooltip>
        </li>
      ) : null}
    </ul>
  );
}
