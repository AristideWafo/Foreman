# Design system — Foreman (proposition à relire)

Statut : **brouillon**. À valider avant d'ajouter ou de refaire un écran (voir `CLAUDE.md`).
Les points marqués **[À trancher]** attendent une décision.

## Principe

Foreman est une conversation qui produit des **cartes** (plan, étapes, résultat). L'utilisateur fait une
chose : dire ce qu'il veut, relire le plan, valider. L'interface s'efface devant ça.

1. **Un champ, une action.** L'accueil est un champ et Entrée. Rien d'autre à comprendre.
2. **Deux clics au plus** pour toute tâche courante. Si une action en demande trois, on revoit l'écran.
3. **Peu d'éléments.** Un écran = un contenu principal + une action principale. Pas de barre latérale, pas
   de menu tant qu'il n'y a pas deux destinations à y mettre.
4. **Le calme.** Neutre et lisible ; la couleur ne sert qu'à signaler un état ou l'action principale.

## Parcours cibles

| Tâche                               | Chemin                                  | Clics |
| ----------------------------------- | --------------------------------------- | ----- |
| Démarrer                            | Accueil : écrire, Entrée                | 0 à 1 |
| Poursuivre                          | Page projet : écrire, Entrée            | 0 à 1 |
| Relire un plan                      | La carte s'affiche dans la conversation | 0     |
| Valider / refuser une étape _(S2+)_ | Deux boutons dans la carte              | 1     |
| Revenir                             | « Accueil »                             | 1     |

Pas de modale pour confirmer : la confirmation est **dans la carte**, avec un libellé explicite.
**[À trancher]** Liste des projets passés : page dédiée ou liste en bas de l'accueil ? Recommandation : liste
en bas de l'accueil (zéro navigation en plus).

## Jetons

À définir **une seule fois** dans `src/index.css` (variables shadcn), jamais ailleurs.

- **Couleurs** : neutre shadcn (`neutral`), clair et sombre. Une couleur d'accent unique (`primary`), réservée
  à l'action principale. États : `destructive` (échec), `muted` (secondaire). Pas de dégradé, pas d'ombre
  marquée (au plus `shadow-xs`).
  **[À trancher]** Accent : noir/blanc par défaut de shadcn (le plus sobre) ou une teinte (ex. indigo, comme
  avant) ? Recommandation : garder le neutre et ajouter l'accent plus tard, si le besoin se confirme.
- **Typographie** : Geist (texte) et Geist Mono (identifiants, étapes). Trois tailles : titre `text-2xl`,
  texte `text-sm`/`text-base`, annotation `text-xs`. Deux graisses : normale et `font-semibold`.
- **Espacement** : échelle Tailwind en multiples de 4 ; pages de largeur `max-w-3xl`, marge `px-4`.
- **Rayons** : un seul rayon de base (`--radius`) ; pas de variantes ad hoc.
- **Icônes** : Heroicons `outline` 16 ou 20 px (`size-4`/`size-5`), toujours avec un texte ou un libellé.

## Composants

Existants (shadcn) : `Button`, `Card`, `Badge`, `Alert`, `Textarea`, `ScrollArea`.
À créer dans `src/components/` quand le besoin apparaît (pas avant) :

| Composant     | Rôle                                             | Usage actuel                 |
| ------------- | ------------------------------------------------ | ---------------------------- |
| `LinkButton`  | Bouton qui est un lien de routeur                | Accueil, 404, erreur projet  |
| `BrandLogo`   | Logo svgl par nom, taille et libellé accessibles | Cartes d'intégration _(S5+)_ |
| `PageShell`   | Largeur, marges et en-tête communs               | Toutes les pages             |
| `StatusBadge` | Statut d'étape avec icône Heroicons              | Cartes de plan               |

Cartes : une famille (`kind`) = un composant dans `features/cards/`, construit à partir de `Card`,
`Badge` et `Button`. Une carte de genre inconnu a toujours un repli.

## États à prévoir pour chaque écran

Chargement (texte court, pas de squelette animé), vide (une phrase qui dit quoi faire), erreur (`Alert`
avec l'action « Réessayer »), reconnexion (une ligne de statut discrète).

## Mouvement

Douceur avant tout, et rien quand c'est possible : 150 à 200 ms, `ease-out`, `opacity`/couleur seulement,
`prefers-reduced-motion` respecté. Apparition d'un message : fondu. Pas de défilement animé, pas de
rebond. Indicateur d'attente : texte + Heroicons `SparklesIcon` en opacité lente.

## Accessibilité

Contraste AA, focus visible, tout utilisable au clavier, cibles tactiles ≥ 40 px sur mobile, textes
d'état annoncés (`role="status"` / `role="alert"`).

## Ce que l'on ne fait pas

Thème personnalisable, tableau de bord, notifications toast, animations d'entrée de page, illustrations.
