# CLAUDE.md — frontend

Complète le `CLAUDE.md` et l'`AGENTS.md` de la racine (couches, sécurité, workflow Git : ils priment).
Ce fichier fixe la **stack** et la **façon de construire l'interface**.

## Stack (non négociable)

| Sujet            | Choix                                                                  | Règle                                                                                                   |
| ---------------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Police           | **Geist** (`@fontsource-variable/geist`, `geist-mono` pour le code)    | Une seule famille ; pas d'autre police                                                                  |
| Thème / DA       | **Thème par défaut de shadcn** (preset `base-nova`, neutre)            | On ne redéfinit ni couleurs, ni rayons, ni ombres ; changer de thème = `shadcn apply`, jamais à la main |
| Composants       | **shadcn/ui** (style `base-nova`, Base UI)                             | On compose avec `src/components/ui/` ; on n'écrit pas de bouton, champ, carte ou alerte à la main       |
| Icônes UI        | **Heroicons** (`@heroicons/react`, `24/outline`)                       | Un seul trait (outline), une seule taille ; pas de `lucide-react`, pas de `24/solid` (voir ci-dessous)  |
| Logos de marques | **svgl** (svgl.app)                                                    | SVG copiés dans `src/assets/logos/`, affichés par le composant `BrandLogo` ; aucune dépendance          |
| Styles           | Tailwind 4, variables CSS de shadcn                                    | Couleurs et rayons via les jetons du thème, jamais de valeur codée en dur                               |
| Données          | TanStack Query, types générés depuis `openapi.json` (`make api-types`) | Jamais de type d'API écrit à la main                                                                    |

## Skill shadcn obligatoire

Pour toute tâche d'interface (ajouter, composer, corriger un composant), l'agent **utilise la skill `shadcn`**
et suit ses règles (`.claude/skills/shadcn/`). Elle donne le contexte du projet, les composants à privilégier
et les primitives de chat (`MessageScroller`, `Message`, `Bubble`, `Trace`).

**Si la skill n'existe pas** (dossier `.claude/skills/shadcn` absent), l'agent l'installe **avant** de
continuer, à la racine du dépôt : `npx skills add shadcn/ui`. Il vérifie ensuite que le dossier existe et
relit la skill. Aucun composant n'est écrit « de mémoire » sans elle.

La CLI `shadcn` n'est pas une dépendance du projet (elle embarque `braces`, vulnérable) : on l'exécute avec `pnpm dlx shadcn@latest`, et le CSS `shadcn/tailwind.css` est copié dans `src/shadcn.css`.

Règles de la skill, déjà appliquées ici :

- On cherche dans le registre (`pnpm dlx shadcn@latest search`) et on lit la doc (`... docs <composant>`)
  avant d'écrire du balisage. Chat : `MessageScroller`, `Message`, `Bubble`, `Trace` ; saisie : `InputGroup` ;
  barres latérales : `Sidebar` (double barre = bloc `sidebar-09`).
- Pas de classes de taille sur les icônes à l'intérieur d'un composant shadcn (`Button`, `Sidebar*`…) : il
  les dimensionne ; dans un `Button`, `data-icon="inline-start"` ou `"inline-end"`.
- `gap-*` et jamais `space-*` ; `size-*` quand largeur = hauteur ; couleurs sémantiques (`bg-primary`…) seulement.

**Heroicons et shadcn.** `shadcn add` génère des imports `lucide-react` ou laisse des `IconPlaceholder`
(Heroicons n'est pas géré par la CLI). Après chaque ajout, remplacez-les par l'équivalent Heroicons, puis
vérifiez que `lucide-react` et `IconPlaceholder` n'apparaissent plus dans `src/` et `package.json`. Un composant
shadcn ne se modifie que pour cela et pour les jetons de mouvement ci-dessous.

## Programmation par composants réutilisables

1. **Avant d'écrire du JSX, cherchez.** `src/components/ui/` (shadcn), puis `src/components/` (composants
   de l'application), puis `src/features/<domaine>/`. Réutilisez ; sinon créez.
2. **Trois emplacements, une direction.** `components/ui` (shadcn, génériques) → `components` (composés,
   sans logique métier : `LinkButton`, `PageHeader`, `AppSidebar`, `BrandLogo`…) → `features/<domaine>`
   (logique métier, appels API, état). Un niveau n'importe jamais un niveau au-dessus.
3. **Deux occurrences du même balisage = un composant.** Pas de classes Tailwind recopiées d'un fichier à l'autre.
4. **Composants petits et sans effet de bord** : props typées, pas d'appel réseau dans `components/`,
   état local seulement quand il est nécessaire. La logique va dans un hook (`useXxx`).
5. **Accessibilité d'office** : libellés, `role` pour les alertes et statuts, focus visible, navigation
   clavier. Le texte venant de l'API s'affiche comme texte, jamais comme HTML.
6. **Pas de dossier fourre-tout** (`utils/`, `common/`, `helpers/`) hors `lib/utils.ts` de shadcn.

## Design system d'abord

**On n'écrit aucun écran avant que `DESIGN.md` soit relu.** Toute nouvelle page ou carte :

1. Se rattache à `DESIGN.md` (échelle typographique, composants, règles d'interaction) ; si un besoin n'y
   est pas, on **modifie `DESIGN.md` d'abord**, puis le code.
2. Se justifie par le **nombre de clics** : une tâche courante se fait en **deux clics ou moins**
   (idéalement un champ + Entrée). Pas de modale quand une zone en ligne suffit, pas d'étape inutile.
3. Reste **sobre** : peu d'éléments par écran, une seule action principale visible, pas de décoration.
4. N'ajoute **aucun contrôle sans effet** (pièce jointe, option…) : on l'ajoute quand le serveur le gère. Une entrée de
   navigation pour une page à venir est permise si elle est **désactivée** et signalée « bientôt » (voir `DESIGN.md`).

## Mouvement

- Animations et transitions **facultatives et douces** : 150 à 200 ms, `ease-out`, uniquement `opacity`,
  `color`, `background-color` ou un léger `transform`. Pas de rebond, pas de boucle infinie ; texte « en cours »
  = `shimmer` de shadcn.
- Pas de `transition-all`, pas d'effet d'enfoncement (`translate`) sur les boutons.
- Tout mouvement respecte `prefers-reduced-motion` (`motion-safe:`).

## Tests et vérifications

- Tests front facultatifs (voir racine), mais au minimum un test de rendu léger par carte ou écran qui prouve le
  critère de fin d'un scénario.
- Avant chaque commit : `pnpm typecheck && pnpm lint && pnpm test && pnpm build`, puis `pnpm format`.
- Une PR qui change l'interface décrit ce qui a été **regardé dans un navigateur** (clair, sombre, mobile),
  ou dit que ce n'est pas fait.
