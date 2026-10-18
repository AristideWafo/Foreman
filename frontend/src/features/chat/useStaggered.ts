import { useEffect, useState } from "react";

const STEP_MS = 450;
const BACKLOG_MAX = 4;

/**
 * Révèle les éléments un à un, pour que chaque composant apparaisse après le précédent.
 * `delayAfter(précédent)` donne l'attente avant l'élément suivant. Un gros retard
 * (historique rechargé) s'affiche d'un coup : on n'anime que le direct.
 */
export function useStaggered<T>(
  items: T[],
  delayAfter: (previous: T) => number = () => STEP_MS,
): T[] {
  const [count, setCount] = useState(0);
  const shown = items.length - count > BACKLOG_MAX ? items.length : count;
  const previous = shown > 0 ? items[shown - 1] : undefined;
  const wait = previous === undefined ? 0 : delayAfter(previous);

  useEffect(() => {
    if (shown >= items.length) return;
    const timer = setTimeout(() => setCount(shown + 1), wait);
    return () => clearTimeout(timer);
  }, [shown, items.length, wait]);

  return items.slice(0, shown);
}
