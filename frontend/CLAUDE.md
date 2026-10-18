# CLAUDE.md — frontend

Complète le `CLAUDE.md` et l'`AGENTS.md` de la racine (couches, sécurité, workflow Git : ils priment).
Ce fichier fixe la **stack** et la **façon de construire l'interface**.

## Stack (non négociable)

| Sujet            | Choix                                                                                      | Règle                                                                                             |
| ---------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------- |
| Police           | **Geist** (`@fontsource-variable/geist`, `geist-mono` pour le code)                        | Une seule famille ; pas d'autre police                                                            |
| Composants       | **shadcn/ui** (style `base-nova`, Base UI)                                                 | On compose avec `src/components/ui/` ; on n'écrit pas de bouton, champ, carte ou alerte à la main |
| Icônes UI        | **Heroicons** (`@heroicons/react`, `24/outline` par défaut, `24/solid` pour un état actif) | Pas de `lucide-react` (voir ci-dessous)                                                           |
| Logos de marques | **svgl** (svgl.app)                                                                        | SVG copiés dans `src/assets/logos/`, affichés par le composant `BrandLogo` ; aucune dépendance    |
| Styles           | Tailwind 4, variables CSS de shadcn                                                        | Couleurs et rayons via les jetons du thème, jamais de valeur codée en dur                         |
| Données          | TanStack Query, types générés depuis `openapi.json` (`make api-types`)                     | Jamais de type d'API écrit à la main                                                              |

**Heroicons et shadcn.** `shadcn add` génère des imports `lucide-react`. Après chaque ajout, remplacez-les
par l'équivalent Heroicons, puis vérifiez que `lucide-react` n'apparaît plus dans `src/` et `package.json`.
Un composant shadcn ne se modifie que pour cela et pour les jetons de mouvement ci-dessous.

## Programmation par composants réutilisables

1. **Avant d'écrire du JSX, cherchez.** `src/components/ui/` (shadcn), puis `src/components/` (composants
   de l'application), puis `src/features/<domaine>/`. Réutilisez ; sinon créez.
2. **Trois emplacements, une direction.** `components/ui` (shadcn, génériques) → `components` (composés,
   sans logique métier : `LinkButton`, `BrandLogo`, `PageShell`…) → `features/<domaine>` (logique métier,
   appels API, état). Un niveau n'importe jamais un niveau au-dessus.
3. **Deux occurrences du même balisage = un composant.** Pas de classes Tailwind recopiées d'un fichier à l'autre.
4. **Composants petits et sans effet de bord** : props typées, pas d'appel réseau dans `components/`,
   état local seulement quand il est nécessaire. La logique va dans un hook (`useXxx`).
5. **Accessibilité d'office** : libellés, `role` pour les alertes et statuts, focus visible, navigation
   clavier. Le texte venant de l'API s'affiche comme texte, jamais comme HTML.
6. **Pas de dossier fourre-tout** (`utils/`, `common/`, `helpers/`) hors `lib/utils.ts` de shadcn.

## Design system d'abord

**On n'écrit aucun écran avant que `DESIGN.md` soit relu.** Toute nouvelle page ou carte :

1. Se rattache à `DESIGN.md` (jetons, composants, règles d'interaction) ; si un besoin n'y est pas, on
   **modifie `DESIGN.md` d'abord**, puis le code.
2. Se justifie par le **nombre de clics** : une tâche courante se fait en **deux clics ou moins**
   (idéalement un champ + Entrée). Pas de modale quand une zone en ligne suffit, pas d'étape inutile.
3. Reste **sobre** : peu d'éléments par écran, une seule action principale visible, pas de décoration.

## Mouvement

- Animations et transitions **facultatives et douces** : 150 à 200 ms, `ease-out`, uniquement `opacity`,
  `color`, `background-color` ou un léger `transform`. Pas de rebond, pas de boucle infinie (sauf l'indicateur
  d'attente, en `opacity`, très lent).
- Pas de `transition-all`, pas d'effet d'enfoncement (`translate`) sur les boutons.
- Tout mouvement respecte `prefers-reduced-motion` (`motion-safe:`).

## Tests et vérifications

- Tests front facultatifs (voir racine), mais au minimum un test de rendu léger par carte ou écran qui prouve le
  critère de fin d'un scénario.
- Avant chaque commit : `pnpm typecheck && pnpm lint && pnpm test && pnpm build`, puis `pnpm format`.
- Une PR qui change l'interface décrit ce qui a été **regardé dans un navigateur** (clair, sombre, mobile),
  ou dit que ce n'est pas fait.
