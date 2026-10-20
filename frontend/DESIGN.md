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

- **Double barre latérale** (bloc shadcn `sidebar-09`) : un **rail d'icônes** et un **panneau** (bouton
  « Nouveau projet », liste des projets). Rail, en haut : Accueil, Projets, Équipes ; en bas : Informations,
  Paramètres, Compte. Toutes les icônes du rail sont centrées sur le même axe. Équipes et les trois icônes du
  bas sont **désactivées** (« bientôt ») : leurs pages n'existent pas encore.
- **Un seul bouton de barre latérale**, dans l'en-tête de page : il replie le tout sur le rail ; sur mobile, seul
  le rail s'ouvre en tiroir.
- Liste des projets : celle du **serveur** (`GET /api/projects`, base de données), pas de liste locale. Un projet
  prend pour titre le début de son premier message ; sans titre, « Sans titre ».
- Contenu : `max-w-3xl`, centré, en-tête commun (`PageHeader`).
- **Badge « Mode mémoire »** : en pied du panneau de la barre latérale, un `Badge` `outline` avec l'icône
  `ExclamationTriangleIcon`, `role="status"` et le texte « Mode mémoire » (le texte seul porte le sens, pas la couleur).
  Une infobulle native (`title`) explique : « Les données sont perdues au redémarrage du serveur. » Il n'apparaît que si
  `GET /healthz` renvoie `persistence = "memory"` ; avec `postgres`, ou si la requête échoue, rien n'est affiché (le
  front ne devine pas). Le panneau est masqué sur mobile (seul le rail s'ouvre), le badge l'est donc aussi.

## Écrans

| Écran                    | Contenu                                                                    | Clics pour la tâche          |
| ------------------------ | -------------------------------------------------------------------------- | ---------------------------- |
| Accueil (nouveau projet) | Salutation, titre « Que voulez-vous faire ? », champ de saisie, 4 exemples | 0 à 1 (Entrée ou un exemple) |
| Projet                   | Conversation, saisie en bas                                                | 0 à 1                        |

L'accueil ne propose volontairement ni pièce jointe, ni choix de style, ni option : rien n'existe encore
côté serveur. On ajoute un contrôle seulement quand il fait quelque chose. Seule exception : les entrées de
navigation demandées pour la suite (Équipes, Informations, Paramètres, Compte), **désactivées** et signalées
« bientôt ».

## Conversation : l'activité de l'agent

Bulle de l'utilisateur : `Bubble` `secondary`. Réponse de l'agent : texte simple (`Bubble` `ghost`).

À l'envoi d'un message, dans l'ordre : la bulle de l'utilisateur apparaît (fondu), puis une **trace** :
« Réflexion en cours » (texte animé, `shimmer`), puis « Réflexion terminée » avec les **outils utilisés**
(« Plan proposé »), puis la **carte plan** (voir « Cartes de plan et d'exécution ») dont les étapes ont une
icône de statut (horloge, en cours, validée, échec).

La trace est une ligne repliable (« Réflexion en cours » avec spinner, ouverte ; « Réflexion terminée en n étapes »,
repliée) dont les étapes apparaissent une à une. Les éléments d'un tour (bulle, trace, texte, carte) sont révélés
l'un après l'autre (`useStaggered`), même avec des données simulées ; un historique rechargé s'affiche d'un coup.
La réflexion reste « en cours » au moins 1,5 s pour être lisible.

Après « Valider le plan », l'exécution ne crée pas de seconde carte : elle s'affiche **dans la carte du plan**
(`foldExecutions`). Les étapes passent en cours puis réussies en direct, et le journal de chaque étape (repliable)
apparaît sous cette étape.

Limite du contrat v1 : le serveur n'envoie ni texte de raisonnement ni appel d'outil. La trace est déduite
de `turn_status` et des cartes. Un vrai raisonnement ou des outils détaillés demandent de nouveaux types
d'événements (évolution additive du contrat), pas un changement d'interface.

## Auteurs et participants (#241)

Au-dessus d'un message utilisateur qui a un `author` : son nom en `text-[0.6875rem]`, `text-muted-foreground`,
aligné sur la bulle, une seule fois par suite de messages du même auteur. Rien pour l'assistant ni l'ancien
historique (sans `author`). À droite de l'en-tête du projet (`PageHeader actions`) : pastilles rondes `size-6`
d'initiales, nuance stable tirée de l'id parmi les jetons `chart-2` à `chart-5` (thème neutre, pas de couleur
codée), 4 au plus puis « +N ». Nom au survol et au focus (`Tooltip`) et en `aria-label`. Participants déduits
des messages du flux ; aucune pastille sans auteur connu.

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

Icônes : **Heroicons `24/outline`**, une seule taille (**18 px**) et un trait de **1,75** partout. C'est imposé par
une règle globale dans `src/index.css` (hors `@layer`, elle l'emporte sur les tailles des composants shadcn) :
on n'écrit donc aucun `size-*` sur une icône. Pas de `24/solid`.

### Inventaire des textes (visuel → classes)

Deux tailles (`text-sm`, `text-xs`) et deux couleurs : **noir** (`foreground`, ce qu'on lit) et **gris**
(`muted-foreground`, ce qui accompagne). Seul le titre d'accueil sort de l'échelle.

| Texte à l'écran                                             | Taille / graisse              | Couleur |
| ----------------------------------------------------------- | ----------------------------- | ------- |
| « Que voulez-vous faire ? »                                 | `text-3xl font-semibold`      | noir    |
| Titre de page, titre de carte (« Plan : … », « Exécution ») | `text-sm font-semibold`       | noir    |
| Bulles de conversation, valeurs des faits (Environnement…)  | `text-sm`                     | noir    |
| Trace de réflexion, « Étapes : n sur m », titres d'étapes   | `text-sm`                     | gris    |
| Description de carte (résumé du plan)                       | `text-sm`                     | gris    |
| Libellés des faits (Budget, Skills…), fournisseur et type   | `text-xs`                     | gris    |
| Détail d'étape (outil · classe · réversibilité), pastille   | `text-xs`, Geist Mono / Badge | gris    |
| Journal d'étape (bloc gris)                                 | `text-xs`, Geist Mono         | noir    |

Pas de gris intermédiaire : une étape en attente n'est pas atténuée, son icône suffit. Ces textes passent par
`CardHeading`, `CollapsibleSection`, `FactList`, `StepList` : on ne règle pas une taille ou une couleur ailleurs.

## Couleurs et formes

Celles de shadcn (thème neutre, clair et sombre) via les variables de `src/index.css` : `primary` pour
l'action principale, `muted` pour le secondaire, `destructive` pour l'échec. Aucune valeur de couleur
écrite dans le code.

## Composants

Composants partagés (`components/`) : `CardHeading` (en-tête de carte), `CollapsibleSection` (ligne repliable),
`reveal` (apparition décalée). Cartes (`features/cards/`) : `StepList`, `FactList`, `ResourceList`, `ClarificationCard`.

Existants : shadcn (`Button`, `Card`, `Badge`, `Alert`, `Textarea`, `InputGroup`, `Sidebar`, `Tooltip`,
`Separator`, `Collapsible`, `Skeleton`, `Sheet`, `ScrollArea`, `MessageScroller`, `Message`, `Bubble`,
`Marker`, `Trace`, `ToggleGroup`) et applicatifs : `LinkButton`, `PageHeader`, `AppSidebar`, `MemoryModeBadge`, `UserRoleBadge`. À créer au besoin :
`BrandLogo` (logos svgl). Une carte = un composant par `kind` dans `features/cards/`, avec repli.

## Cartes de plan et d'exécution (Semaine 2)

Deux cartes dans la conversation, rendues depuis les événements `card` (remplacées par `card_id`, jamais
dupliquées). Ce sont des `Card` shadcn : titre + état en en-tête, contenu, action en pied. Tout texte de l'API
est du **texte** (jamais HTML) ; un lien n'est cliquable que s'il est en `http(s)`.

**Carte plan** : titre, résumé, badge de statut (proposé, validé, invalidé, expiré, exécuté) ; étapes (une
`TraceLine` par étape, icône de statut, puis `outil · classe · réversibilité` en `text-xs`) ; une liste de
définitions `text-xs`/`text-sm` : environnement, autonomie, stack, Skills (nom, version), ressources attendues,
empreinte (`sha256:` + 12 caractères, `…`, en Geist Mono, valeur complète en infobulle native).
Action unique : **« Valider le plan »** (`Button` par défaut), visible seulement si `approvable` et statut
`proposed` : **un clic**. Pendant l'appel : bouton désactivé, `aria-busy`. Succès (201 ou 200) : ligne
`role="status"` « Plan validé » et bouton retiré. Échec : `Alert` (`role="alert"`) en français, sans détail
technique ; sur 409 ou 404 le bouton reste désactivé jusqu'à ce que le serveur réémette la carte plan
(le front ne devine pas l'état). Tant que le serveur répond 501 : « La validation n'est pas encore disponible. »

**Carte exécution** : titre « Exécution », badge d'état (`role="status"`), étapes dynamiques (mêmes lignes que le
plan), journal (lignes en Geist Mono, `role="log"`, focalisable au clavier, défilement interne), budget (appels
d'outils utilisés sur le maximum, durée écoulée sur le maximum), niveau d'autonomie, ressources créées (lien
`http(s)` ou texte seul), résultat (résumé et liens). Aucune action : tout est lecture.

Le composant partagé `StepList` rend les étapes des deux cartes ; `ExternalLink` rend tout lien venu de l'API.

## Relancer un plan bloqué

Sur une exécution `blocked` ou `failed_compensated`, le pied de la carte (plan avec exécution repliée, ou
exécution seule) montre un texte d'aide (« les ressources déjà créées sont réutilisées ») et un `Button`
`outline` « Relancer le plan » (`ArrowPathIcon`, `data-icon="inline-start"`). L'action renvoie par
`POST /api/projects/{id}/messages` (même appel que le chat) **le dernier message utilisateur qui précède la
carte** : le flux d'événements n'expose aucun lien message -> plan. Le nouveau plan arrive par le flux, comme
pour tout message. Pendant l'envoi : bouton désactivé, `aria-busy` (donc une seule relance à la fois) ; succès :
ligne `role="status"` ; échec : `Alert` destructive. Affiché **uniquement sur la dernière carte plan ou
exécution** de la conversation (jamais sur l'historique, ni sur une exécution réussie ou en cours) ; dès que le
nouveau plan est émis, il devient la dernière carte et l'action disparaît.

## Carte de clarification (Semaine 3)

Rendue depuis l'événement `card` de `kind = "clarification"` (remplacée par `card_id` à chaque réponse, jamais
dupliquée). C'est une `Card` shadcn (`CardHeading` : icône `QuestionMarkCircleIcon`, titre « Clarification »,
description « Précisez ces points pour que le plan soit complet. »). Les textes du modèle (`prompt`) et les options
sont affichés comme **texte**, jamais comme HTML ; les options sont **imposées par le serveur**, le front n'en
invente aucune.

Une question = un `fieldset` (légende = la question, `text-sm`), puis :

- **Ouverte, avec options** : un `ToggleGroup` (`outline`, choix unique, `flex-wrap`) ; l'option choisie porte
  une coche `CheckIcon` (le sens ne repose pas sur la couleur). Deux boutons : **« Répondre »** (`Button` par
  défaut, désactivé tant qu'aucune option n'est choisie) et **« Reporter »** (`Button` `outline`). Réponse en
  **deux clics** (une option, « Répondre ») ; report en **un clic**.
- **Ouverte, sans option** (le contrat dit « vide = réponse libre ») : un `Input` libellé par la question à la
  place du groupe d'options, mêmes boutons.
- **Répondue** : ligne `role="status"` « Réponse : _valeur_ » avec `CheckIcon`, plus de bouton.
- **Reportée** : ligne `role="status"` « Reportée » avec `MinusCircleIcon`, plus de bouton.
- **Envoi en cours** : boutons désactivés, `aria-busy`, libellé « Envoi en cours… ».
- **Erreur** : `Alert` (`role="alert"`) en français, sans détail technique. `question_closed` (déjà répondue) et
  404 : boutons désactivés jusqu'à ce que le serveur réémette la carte (le front ne devine pas l'état, ne
  réessaie pas). `turn_in_progress` : message « Une réponse est déjà en cours », sans réessai automatique ; le
  développeur peut recliquer. 422 : « Cette réponse n'est pas acceptée. ».

Les questions sont indépendantes : chaque réponse relance un tour (202) ; pendant ce tour, les autres questions
restent ouvertes et reprennent leur état normal à la carte réémise. Aucun contrôle sans effet : tout appelle
`POST /api/projects/{id}/questions/{question_id}`.

## Carte d'approbation (Semaine 4)

Rendue depuis l'événement `card` de `kind = "approval"` (remplacée par `card_id` à chaque changement de `status`,
jamais dupliquée). C'est une `Card` shadcn (`CardHeading` : icône `ShieldCheckIcon`, titre « Approbation
administrateur », description « Ce plan vise la production : un administrateur doit l'approuver. »). Une `FactList` :
environnement, demandé par, règle, empreinte courte (comme la carte plan). Tout est du texte.

Le rôle de l'utilisateur vient de `GET /api/me` (`useMe`), jamais d'une règle du front : le serveur reste seul juge
(403 `forbidden` si le rôle ne suffit pas).

- **Rôle dans `approver_roles` et `status = pending`** : deux boutons, **« Approuver »** (`Button` par défaut, un clic)
  et **« Refuser »** (`outline`). Pendant l'appel : boutons désactivés, `aria-busy`.
- **Autre rôle (ou rôle pas encore connu), `pending`** : ligne `role="status"` « En attente d'un administrateur », sans bouton.
- **Approuvée** : ligne `role="status"` « Approuvée par _nom_ » (`CheckIcon`). **Refusée** : « Refusée par _nom_ »
  (`MinusCircleIcon`). Plus de bouton.
- **Erreur** : `Alert` (`role="alert"`) en français, sans détail technique. 409 et 404 : boutons désactivés jusqu'à ce
  que le serveur réémette la carte (le front ne devine pas l'état). 403 : « Votre rôle ne permet pas cette décision. ».

**Carte plan** : si `admin_approval_required`, l'action devient **« Valider et transmettre à l'admin »** ; sur 202
(`ApprovalPending`), la ligne de statut dit « Validé. En attente d'un administrateur. ».

## Administration (`/admin`) et équipes

Entrée « Administration » dans le rail, visible si `/api/me` donne `org_admin` ou `team_admin` d'une équipe
partagée (aide visuelle : le serveur refuse le reste). Un autre rôle voit « Cette page est réservée aux
administrateurs. ». Trois onglets (`Tabs`) : Équipes (création réservée à l'org_admin, premier admin
obligatoire), Membres (rôle par équipe, ajout, retrait, désactivation), Invitations (lien copiable affiché une
seule fois, avec avertissement). Rétrograder, retirer, désactiver et révoquer passent par un `AlertDialog` de
confirmation. Les listes déroulantes sont des `<select>` natifs (`NativeSelect`). Les erreurs 403/409
(`last_admin`, `last_team_admin`) sont traduites en messages clairs, jamais le détail serveur.

Accueil : sélecteur « Équipe du projet » (équipes de `/api/me`, « Équipe par défaut » = choix du serveur).
Barre latérale : filtre « Filtrer par équipe » dans la liste des projets, à partir de deux équipes.

## Badge nom et rôle (barre latérale)

Pied du panneau de projets : le nom (tronqué si long) et un `Badge` `secondary` avec le rôle en français
(Développeur, Admin d'équipe, Admin d'organisation), lus via `useMe` (`/api/me`). Pendant le chargement ou
après un échec : un `Skeleton` discret, sans message d'erreur. Sur mobile le panneau est masqué : le nom et
le rôle sont alors dans l'infobulle de l'entrée « Compte » du rail. Aucune décision d'accès n'en découle.

## Ressources déjà présentes (Semaine 5)

`ResourceList` affiche un `Badge` `secondary` « déjà présente » après le type de chaque ressource dont
`reused === true` (champ facultatif de `ResourceRef`). Rien d'autre ne change : même liste, même lien.

Le résumé de l'exécution (« N ressources déjà présentes, aucune créée ») est écrit par le serveur et affiché tel quel
dans « Résultat » ; le front n'applique aucune règle de décompte ni de wording.

## Plan invalidé ou expiré (Semaine 6)

Quand `PlanCardData.status` vaut `invalidated` ou `expired` (et qu'il n'y a pas d'exécution), la carte plan affiche en
tête de contenu une `Alert` par défaut (`ExclamationTriangleIcon`). Titre = la raison (`invalidation.reason`, libellés de
`vocabulary.ts`) : « Le catalogue a changé », « Le projet a changé depuis ce plan », « Refusé par un administrateur »,
« Plan expiré ». Description : la liste des `invalidation.changes` (« Référentiel : infra-staging », kind en français puis
nom), puis une phrase : la dérive chez les fournisseurs relève d'un autre contrôle, fait à l'exécution.

- **Pas de bouton « Valider »** : le serveur envoie `approvable: false`.
- **Pied de carte « Refaire le plan »** (`RetryPlan`, bouton `outline`, `ArrowPathIcon`) : renvoie le dernier message
  utilisateur. Proposé seulement sur le dernier plan de la conversation (`findRetry`), jamais sur un plan déjà remplacé.
- **Carte d'approbation** : `status = expired` ou `invalidated` affiche « Expirée » / « Invalidée » (`role="status"`),
  sans bouton.
- Aucune couleur brute ; tokens shadcn, clair, sombre et mobile comme le reste.

## États d'un écran

Chargement (une ligne de texte), vide (une phrase qui dit quoi faire), erreur (`Alert` + « Réessayer »),
reconnexion (une ligne de statut).

## Mouvement

150 à 200 ms, `ease-out`, opacité et couleur seulement ; `prefers-reduced-motion` respecté
(`motion-safe:`). Apparition d'un message : fondu. Texte « en cours » : `shimmer` de shadcn. Seule boucle permise : le spinner d'une étape « en cours ». Pas de
rebond ni d'effet d'enfoncement.

## Accessibilité

Contraste AA, focus visible, tout au clavier, cibles tactiles suffisantes sur mobile, `role="status"` et
`role="alert"` pour les états.

## Hors périmètre

Thème personnalisé, tableau de bord, toasts, illustrations, pièces jointes et choix de modèle (aucun
support serveur).
