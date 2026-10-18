# Design system — Foreman

Statut : **v1, à relire**. Règle : on ne crée pas d'écran avant d'avoir relu ce fichier (voir `CLAUDE.md`).
Le design est celui de **shadcn/ui, tel quel** (preset `base-nova`, thème neutre, police Geist). On ne
redéfinit ni couleurs, ni rayons, ni ombres.

## Principes

1. **Un champ, une action.** L'accueil est un champ et Entrée (ou un clic sur un exemple).
2. **Deux clics au plus** pour toute tâche courante.
3. **Peu d'éléments.** Un écran = un contenu principal + une action principale.
4. **Doux.** Pas d'animation décorative ; seulement ce qui explique un changement d'état.

## Structure de l'application

- **Double barre latérale** (bloc shadcn `sidebar-09`) : un **rail d'icônes** (Accueil, Projets) et un
  **panneau** (bouton « Nouveau projet », liste des projets). Le bouton de barre latérale replie le tout
  sur le rail ; sur mobile, seul le rail s'ouvre en tiroir.
- Liste des projets : **locale au navigateur** (le serveur n'a pas encore de route de liste). Elle peut
  contenir un projet que le serveur a oublié (redémarrage) : l'ouvrir affiche « Projet introuvable ».
- Contenu : `max-w-3xl`, centré, en-tête commun (`PageHeader`).

## Écrans

| Écran                    | Contenu                                                                    | Clics pour la tâche          |
| ------------------------ | -------------------------------------------------------------------------- | ---------------------------- |
| Accueil (nouveau projet) | Salutation, titre « Que voulez-vous faire ? », champ de saisie, 4 exemples | 0 à 1 (Entrée ou un exemple) |
| Projet                   | Conversation, saisie en bas                                                | 0 à 1                        |

L'accueil ne propose volontairement ni pièce jointe, ni choix de style, ni option : rien n'existe encore
côté serveur. On ajoute un contrôle seulement quand il fait quelque chose.

## Conversation : l'activité de l'agent

À l'envoi d'un message, dans l'ordre : la bulle de l'utilisateur apparaît (fondu), puis une **trace** :
« Réflexion en cours » (texte animé, `shimmer`), puis « Réflexion terminée » avec les **outils utilisés**
(« Plan proposé »), puis la **carte de plan** avec le statut de chaque étape.

Limite du contrat v1 : le serveur n'envoie ni texte de raisonnement ni appel d'outil. La trace est déduite
de `turn_status` et des cartes. Un vrai raisonnement ou des outils détaillés demandent de nouveaux types
d'événements (évolution additive du contrat), pas un changement d'interface.

## Typographie, graisses et icônes (une seule échelle)

| Rôle                    | Classes                                 | Où                                                 |
| ----------------------- | --------------------------------------- | -------------------------------------------------- |
| Titre d'accueil         | `text-3xl font-semibold tracking-tight` | Accueil seulement                                  |
| Titre de page / panneau | `text-sm font-semibold`                 | `PageHeader`, en-tête de barre latérale            |
| Texte                   | `text-sm` (graisse normale)             | Tout le reste, messages compris                    |
| Libellé d'action        | `font-medium`                           | Boutons, entrées de menu (déjà fournis par shadcn) |
| Annotation              | `text-xs`                               | Aides, étiquettes de section                       |

Deux graisses en plus de la normale : `font-medium` (actions) et `font-semibold` (titres). Pas de `font-bold`.
Police : **Geist** (texte), **Geist Mono** (code, identifiants).

Icônes : **Heroicons `24/outline`**, un seul trait, une seule taille (16 px). Les composants shadcn
dimensionnent leurs icônes (pas de `size-*` dedans) ; hors composant, `size-4`. Pas de `24/solid`.

## Couleurs et formes

Celles de shadcn (thème neutre, clair et sombre) via les variables de `src/index.css` : `primary` pour
l'action principale, `muted` pour le secondaire, `destructive` pour l'échec. Aucune valeur de couleur
écrite dans le code.

## Composants

Existants : shadcn (`Button`, `Card`, `Badge`, `Alert`, `Textarea`, `InputGroup`, `Sidebar`, `Tooltip`,
`Separator`, `Collapsible`, `Skeleton`, `Sheet`, `ScrollArea`, `MessageScroller`, `Message`, `Bubble`,
`Marker`, `Trace`) et applicatifs : `LinkButton`, `PageHeader`, `AppSidebar`. À créer au besoin :
`BrandLogo` (logos svgl). Une carte = un composant par `kind` dans `features/cards/`, avec repli.

## États d'un écran

Chargement (une ligne de texte), vide (une phrase qui dit quoi faire), erreur (`Alert` + « Réessayer »),
reconnexion (une ligne de statut).

## Mouvement

150 à 200 ms, `ease-out`, opacité et couleur seulement ; `prefers-reduced-motion` respecté
(`motion-safe:`). Apparition d'un message : fondu. Texte « en cours » : `shimmer` de shadcn. Pas de
rebond ni d'effet d'enfoncement.

## Accessibilité

Contraste AA, focus visible, tout au clavier, cibles tactiles suffisantes sur mobile, `role="status"` et
`role="alert"` pour les états.

## Hors périmètre

Thème personnalisé, tableau de bord, toasts, illustrations, pièces jointes et choix de modèle (aucun
support serveur).
