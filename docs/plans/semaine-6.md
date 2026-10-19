# Plan — Semaine 6 : scénario S12 (approbation sur le hash, plan invalidé si l'état change, expiration)

Plan écrit par l'agent `Plan` (Opus) à partir de l'état réel de `prod` (0.14.0). Il suit le format de `docs/plans/semaine-5.md`. Pour le back-end : 1 à 3 tests par fonctionnalité. `migrations/` reste relu attentivement. `gateway/` ne change pas (voir D4).

## État de départ (vérifié dans le code)

| Élément | État |
| --- | --- |
| Hash (`core/planning.py`) | `PlanContent` (`foreman.plan/1`) contient déjà `policy_sha256`, le `sha256` de chaque référentiel et de chaque Skill, et `tool_version` par étape. **Personne ne les compare au catalogue courant** : un plan proposé avant un redéploiement reste approuvable après |
| Approbation | Les dépôts vérifient `plan_hash_mismatch`, `plan_not_approvable` et `execution_in_progress`. La clé étrangère `approvals(plan_id, plan_hash)` existe. La gateway vérifie `plan_not_approved` / `plan_hash_mismatch` (`_check_plan`) et rejoue la matrice **courante** à chaque appel |
| `invalidated` | N'est écrit que par `reject_admin` (D6 de la semaine 4). Aucune raison n'est stockée |
| Expiration | `PLAN_TTL = 24 h`, `expires_at` est posé par `Planner` (horloge injectable). **`expired` n'est jamais écrit** : il est seulement affiché par `_reissue_plan_card`. Deux horloges coexistent : le dépôt en mémoire utilise `clock()`, PostgreSQL utilise `sa.func.now()` (`_locked_plan`), donc l'expiration n'est pas testable sur PostgreSQL sans l'horloge réelle. Un plan `dev_approved` qui expire garde sa carte d'approbation `pending`, cliquable jusqu'au 409 |
| Catalogue | Chargé une seule fois par `configure` (pas de rechargement à chaud). Il ne change donc qu'au redémarrage ou au redéploiement |
| Front | `planStatusLabel` connaît « Invalidé » et « Expiré ». Rien n'explique pourquoi. `RetryPlan` existe déjà (« Relancer le plan »), mais seulement pour une exécution `blocked`. `ApprovalCard` ne connaît que `pending`, `approved` et `rejected` |
| Tickets du jalon 6 | #43 (approbation sur le hash, invalidation, expiration ; P1 ; il a un `## Critère de fin`) ; #44 (scénario S12 ; P1 ; écrit au format « **Fin :** ») ; #45 (carte « plan invalidé » ; P1, `track:front`) |

## Ce que veut dire « l'état change » dans S12, et ce qui relève de S5

- **Dans S12 : la base du plan**, c'est-à-dire l'état structuré que Foreman détient au moment où le plan est proposé :
  1. le **catalogue** : matrice (`policy_sha256`), référentiels, Skills, versions d'outils ;
  2. le **registre du projet** : ressources vivantes, qui changent quand une autre exécution du projet aboutit ou compense.
- **Hors S12, dans S5 (dérive)** : l'**état observé** chez les fournisseurs (GitLab, serveur), lu avant chaque écriture. Cela couvre `drift_detected`, `observed_state`, les trois options et la remédiation admin (#55). S12 n'appelle aucun adaptateur.
- **Hors S12** : le rôle du demandeur. Il est déjà relu à chaque approbation et à chaque appel, et un changement donne `policy_denied`, pas une invalidation.

## Décisions à trancher (recommandation en premier)

| # | Question | Recommandation |
| --- | --- | --- |
| D1 | Comment figer la base | `PlanContent` passe en `foreman.plan/2` avec un champ `basis: {registry_sha256}`. Ce hash est calculé à la proposition sur les `(provider, resource_type, external_id)` triés de `registry.list_for_project`. Avec ce que le plan contient déjà (catalogue), **le hash approuvé couvre la base** : approuver le hash, c'est approuver le plan dans cet état. Aucune migration pour la base. Un ancien plan `/1` n'est plus validable (`plan_not_approvable`) : il expire de toute façon sous 24 h |
| D2 | Où détecter | (a) À la **validation du développeur** et à l'**approbation admin**, avant toute écriture : c'est là que l'attente est longue. (b) **Pas** à chaque appel de la gateway, pour deux raisons : la gateway applique déjà la matrice courante (le plus strict des deux s'impose), et le registre change par l'exécution elle-même. (c) Le contrôle au démarrage du moteur, lors d'une reprise après un redéploiement sans aucune étape réussie, est un ticket P3 qui peut glisser |
| D3 | Écart « significatif » (F4) | Au PoC, **tout** écart de base invalide le plan, sans seuil. Le seuil est en v1 (P3). Le nouveau plan est sans risque grâce à S11 : les ressources déjà présentes sont réutilisées |
| D4 | Fonction de comparaison | `core/planning.py` : `plan_changes(content, catalog, registry_rows) -> list[PlanChange]`, fonction pure. `PlanChange` vaut `{kind: policy\|referential\|skill\|tool\|registry, name}`, avec des noms du catalogue seulement, jamais une valeur. La gateway ne change pas |
| D5 | Persister l'invalidation | **Migration 0005** : `plans.invalidation jsonb NULL` (`{reason, changes}`), avec un `CHECK` `(status = 'invalidated') = (invalidation IS NOT NULL)`. Les lignes déjà refusées par un admin reçoivent `{reason: admin_rejected}`. Raisons possibles : `admin_rejected`, `catalog_changed`, `project_changed`. Une ligne d'audit (`actor_kind: system`, `decision: invalidated` ou `expired`, `rule_id` = raison) est écrite dans la **même transaction** : le journal suffit à reconstituer l'histoire du plan |
| D6 | Transitions du dépôt | `PlanStore.invalidate(project_id, plan_id, plan_hash, invalidation, now)` : passe de `proposed` ou `dev_approved` (sans exécution) à `invalidated`. Elle est idempotente (`created`) et vérifie le hash. Les décisions reçoivent **`now` de l'horloge injectée** du service : on supprime `sa.func.now()` de `_locked_plan`, il ne reste qu'une source de temps, testable sur les deux backends |
| D7 | Expiration | Elle est **écrite** (`expired`), avec une audit, dès qu'une décision tombe sur un plan échu, puis par `expire_due(now)` : au démarrage (comme la reprise), puis toutes les 5 min dans le cycle de vie de l'application. La boucle n'est pas testée, la fonction l'est avec une horloge fixe. La durée reste fixée à 24 h (la rendre configurable par environnement dans la matrice est P3). Une fois l'exécution créée, l'expiration ne s'applique plus |
| D8 | Contrat HTTP | Aucun nouveau code : 409 `plan_not_approvable` reste la réponse pour un plan invalidé ou expiré. La raison passe par la carte plan réémise, ce que le front fait déjà. La carte n'est réémise **qu'à la transition** (`created`), donc un rejeu n'inonde pas le flux |
| D9 | Concurrence | Entre le contrôle de la base et l'écriture, seule une autre exécution peut changer le registre. L'unicité « une exécution active par projet » donne alors `execution_in_progress`, et l'admin refait le contrôle. Aucun verrou nouveau |

## Volet agentique

- **Skills, prompt, matrice, budgets, outils** : inchangés (ni classe ni réversibilité ne bougent).
- **`Provider`** : aucun nouvel enregistrement. S12 **rejoue `s01.yaml`** deux fois (même message, comme S11).
- **Fakes** : inchangés. Le « redéploiement avec catalogue modifié » est simulé dans le test par une copie du catalogue dans `tmp_path`, avec un octet changé dans `infra-staging.yaml`, chargée par `load_catalog`. Les services sont reconstruits sur les **mêmes** dépôts et le même journal.

## Volet back-end

- **Contrats (ajouts, `v: 1`)** : `PlanCardData.invalidation?: {reason, changes[≤20]}` ; `ApprovalCardData.status` reçoit en plus `expired` et `invalidated` ; `PlanView.invalidation?`. Lancer `make api-types`.
- **Modules** :
  - `core/planning.py` : `basis`, `plan_changes`, `Planner` reçoit `ResourceRegistry` ;
  - `core/approval.py` : contrôle de la base dans `approve` et `approve_admin`, appel à `invalidate`, cartes plan et approbation réémises, `expire_due` ;
  - `core/store.py` : `PlanRecord.invalidation`, `invalidate`, `expire_due`, paramètre `now` ;
  - `infra/in_memory.py` et `infra/db/plans.py` ;
  - `bootstrap/configure.py` : `Planner(catalog, stores.plans, stores.registry)` ;
  - `surfaces/web/app.py` : balayage au démarrage et périodique, via `TaskRegistry`.
- **Migration `0005_plan_invalidation`** (relecture propriétaire) : colonne, remplissage de `admin_rejected`, `CHECK`, `downgrade` testé sur un vrai PostgreSQL. Faire un `pg_dump` avant le déploiement.
- **Sécurité** : `changes` ne contient que des noms du catalogue et des types de ressource (aucun identifiant externe, aucun contenu de référentiel). Erreurs opaques. Aucun appel bloquant. Le refus a lieu avant toute écriture d'approbation.

## Volet front-end

- **DESIGN.md** : nouvelle section « Plan invalidé ou expiré (Semaine 6) ».
- **`PlanCard`** : pour `invalidated` ou `expired`, une `Alert` affiche la raison (« Le catalogue a changé », « Le projet a changé depuis ce plan », « Refusé par un administrateur », « Plan expiré ») et la liste des `changes`. Pied de carte : **« Refaire le plan »**, qui réutilise `RetryPlan` avec le message d'origine, élargi aux plans invalidés et expirés dans `ProjectPage`. Le bouton « Valider » disparaît (`approvable: false`, déjà décidé par le serveur).
- **`ApprovalCard`** : affiche « Expirée » ou « Invalidée », sans boutons.
- **`vocabulary.ts`** : libellés des raisons.
- **Types** régénérés ; fixture `s12-events.json` (`make s12-fixture`) ; test de rendu léger.

## Scénario S12 (`tests/e2e/s12_run.py`, en mémoire, horloge injectée)

1. **Projet modifié** : message S1, puis le plan v1. Même message, puis le plan v2 (même contenu, même base). On valide v2 et l'exécution finit `succeeded` (6 ressources). On valide ensuite v1 : réponse 409 `plan_not_approvable`, carte v1 `invalidated` (`project_changed`, `changes: [registry]`), **aucune exécution créée**, une audit `invalidated`. Un nouveau plan v3 est validé et finit `succeeded`, avec ses ressources `reused`.
2. **Catalogue modifié (S10, admin)** : le développeur valide (202). « Redéploiement » avec un référentiel modifié. L'admin approuve : 409, carte plan `invalidated` (`catalog_changed`, `referential: infra-staging`), carte d'approbation `invalidated`.
3. **Expiration** : on avance l'horloge de 24 h + 1 s. `expire_due` passe le plan en `expired` et émet ses cartes (plan et approbation). Une validation ensuite donne 409, sans carte en double.
4. Invariants : `seq` contigus, aucun secret, registre sans doublon.

## Pile de PR (deux pistes : back en série ; front dès PR-A fusionnée)

| PR | Branche (base) | Contenu | Ticket | Prio | Critère de fin observable |
| --- | --- | --- | --- | --- | --- |
| PR0 | `docs/plan-semaine-6` (prod) | Ce plan, ROADMAP (S6 en cours), critères de #43, #44 et #45 | à créer | P0 | Plan fusionné, #43, #44 et #45 au format standard |
| PR-A | `feat/contract-s12` (prod) | `invalidation`, statuts de la carte d'approbation, `openapi.json`, types TS | à créer | P0 | Contrôle de dérive OpenAPI vert |
| PR-B | `feat/plan-invalidation-store` (PR-A) | D5 à D7 côté dépôts, migration 0005, `now` injecté | #43 | P1 | Contrat des dépôts (deux backends) : `invalidate` et `expire_due` sont idempotents ; 0005 remplit les refus existants |
| PR-C | `feat/plan-basis` (PR-B) | D1, D2, D4 : `foreman.plan/2`, `plan_changes`, contrôle dans `ApprovalService` | #43 | P1 | Un registre ou un catalogue modifié donne 409 et `invalidated`, sans exécution |
| PR-D | `test/s12-plan-invalide` (PR-C) | `s12_run.py`, `test_s12_plan_invalide.py`, `make s12-fixture` | #44 | P1 | Test vert en CI |
| PR-E | `feat/front-s12-card` (PR-A, puis le fixture de PR-D) | Alerte, « Refaire le plan », statuts d'approbation | #45 | P1 | Carte « plan invalidé » rendue depuis `s12-events.json` (test de rendu) |
| PR-F | `feat/plan-expiry-sweep` (PR-B) | Balayage au démarrage et périodique, carte d'approbation `expired` | à créer | P2 | Test avec horloge fixe : plan échu `expired` et 2 cartes émises |

**Ce qui peut glisser, dans l'ordre** : PR-F (l'expiration paresseuse de PR-B suffit à S12), puis le contrôle au démarrage du moteur. S12 n'est **fini** qu'avec PR-D **et** PR-E.

## Tests (ordre de CLAUDE.md)

- **Sécurité** : un plan dont la base a changé n'est jamais approuvé, ni par le développeur ni par l'admin, et aucune exécution n'est créée. Le rejeu de la route répond toujours 409 (PR-C).
- **Contrat** : dérive OpenAPI ; aller-retour de `invalidation` (PR-A) ; 0005 avec montée, descente et `CHECK` (PR-B, vrai PostgreSQL).
- **Nominal** : S12 en mémoire (PR-D).
- **Régression** : l'expiration sur PostgreSQL suit l'horloge injectée et non `now()` (PR-B). Le test de `test_execution.py:311` est adapté, puisque `expired` est maintenant persisté.

## Impact sur les contrats figés

- **Ajouts seulement** : `invalidation`, deux valeurs de `ApprovalCardData.status`, `PlanView.invalidation`.
- **Changements de comportement à signaler dans les PR** : `expired` est écrit en base ; le schéma de plan passe à `foreman.plan/2` (nouveau champ `basis`), donc les hash changent pour les nouveaux plans ; un plan `/1` encore en attente n'est plus approuvable.
- Aucun nouveau code HTTP. Le ticket #125 (fermé) renvoie déjà `plan_not_approvable` pour un plan expiré : #43 s'appuie dessus et ne retient pas le code `expired`.

## Risques

- Les plans `/1` en attente au moment du déploiement deviennent inapprouvables : déployer sans plan en attente, ou accepter de les relancer.
- Un YAML d'outil modifié **sans changer sa version** n'est pas détecté. Ticket P3 : empreinte par outil dans le catalogue.
- La base ne couvre que le registre : une dérive manuelle chez GitLab n'invalide rien, c'est le rôle de S5 (#55). À dire dans la carte et dans la documentation.
- Le balayage périodique ajoute une tâche de fond : il doit être borné, s'arrêter proprement au `shutdown`, et ne pas planter si le stockage est indisponible.
- 0005 réécrit des données en ligne : `pg_dump` avant, `downgrade` testé.

## Côté serveur (propriétaire)

- #190 : contrôle Traefik avant `proxy_header`.
- #105 : flux SSE derrière Traefik.
- Déployer 0005 après un `pg_dump`, puis jouer S12 à la main : modifier un référentiel, redéployer, approuver un plan ancien. Résultat attendu : carte « plan invalidé ».

## Tickets (jalon « PoC S6 — Semaine 6 : scénario S12 », sauf mention)

- **À créer** : plan S6 (P0) ; contrat S12 (P0) ; balayage d'expiration et notification (P2) ; contrôle de la base au démarrage du moteur lors d'une reprise (P3) ; empreinte par outil dans le catalogue (P3) ; seuil « écart significatif » (F4) et durée de validité par environnement (P3, v1).
- **À corriger** :
  - #44 : remplacer « **Fin :** » par un `## Critère de fin` (`test_s12_plan_invalide.py` vert en CI, carte « plan invalidé » rendue depuis `s12-events.json`) et lister la dépendance vers #43 ;
  - #43 : définir « changement d'état » comme la **base** (catalogue et registre du projet), préciser que la dérive observée relève de S5 (#55), lier la migration 0005 et ajouter `## Dépendances` (#125) ;
  - #45 : préciser « affiche la raison et les `changes`, bouton Refaire le plan », avec un test de rendu comme preuve ;
  - à décider par le propriétaire : #43 en P0 (il bloque #44 et #45) ou en P1.
- **Liés (hors jalon)** : #61 et #62 (jeu d'évaluation) devront inclure S12 une fois vert.
