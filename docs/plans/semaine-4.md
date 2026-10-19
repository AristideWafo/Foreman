# Plan — Semaine 4 : rôles, matrice R1 à R10 et scénario S10 (production sans droit)

Plan écrit par l'agent `Plan` (Opus) d'après l'état réel de `prod`. Les tests back sont unitaires : 1 à 3 par fonctionnalité, seulement les plus utiles. La revue indépendante par un agent reste désactivée sur décision du propriétaire. `policy/`, `gateway/` et `migrations/` gardent une relecture attentive du propriétaire.

Skills de méthode : `backend-service-builder`, `frontend-application-builder` avec la skill `shadcn`, `doc-coauthoring`. On ne prend pas `docker-builder` : le seul fichier de `deploy/` touché porte un label Traefik.

## État de départ (vérifié dans `prod`)

| Élément | État |
| --- | --- |
| Semaine 3 : journal persisté (0002), clarification, S2, carte de clarification | **fait** (#33, #34 et #35 fermés). La ROADMAP indique encore « en cours » : à corriger dans PR0 |
| Matrice YAML (`catalog/policy/matrix.yaml`) | **partielle** : R1, R2 et R6 seulement, un seul environnement (`staging`) |
| Validation de la matrice (`core/catalog.py`) | **existe** : `RULE_BINDINGS` connaît déjà R1 à R10 ; une écriture n'est jamais `allow` ; `plan_approved` est obligatoire sur `write_registry` ; la règle doit être liée à sa classe et à son environnement. **R3 et R5 de la spec, écrits tels quels, sont refusés au chargement** (R3 est `allow` sur une écriture ; R5 n'a pas de classe et n'a pas `plan_approved`) |
| Évaluation (`core/policy/matrix.py`) | **existe** : première règle qui correspond, refus par défaut, règle « presque applicable » gardée pour l'audit, `effective_level`. **Bogue** : `never_autonomous` renvoie `Deny` dès que la règle correspond, donc R10 refuserait toujours. `admin_approval_required` n'ajoute pas `admin_approved` aux `requires`. `org_ceiling` n'est pas utilisé |
| Gateway (`core/gateway/pipeline.py`) | **existe** : 10 étapes. Le rôle est **fixe** (`DEFAULT_ROLE = "developer"`, un par processus). Un environnement qui exige un admin donne `policy_denied`. Seul `plan_approved` peut être satisfait, et seul le statut `dev_approved` est accepté. **Pas de code `approval_required`** |
| Approbation (`core/approval.py`, `PlanStore.approve`) | **développeur seulement**. Si l'admin est requis, la réponse est `plan_not_approvable` (« validation d'un admin : en S10 »). L'approbation crée l'exécution dans la même transaction. La route n'accepte que `decision: "approved"` |
| Table `approvals` (0001) | **prête** : `kind` (`developer`, `admin`…), `decision` (`approved`, `rejected`), clé étrangère sur `(plan_id, plan_hash)`, index unique `(plan_id, kind)` sur les lignes approuvées |
| Identités | **une seule** : `DEV_USER_ID` et `DEV_TEAM_ID` insérés au démarrage, sans table `memberships` ni rôle. `WEB_USER_ID = "web-anonymous"` (une chaîne) dans `api.py`. `plans.requested_by` existe mais n'est jamais rempli (absent de `NewPlan` et de `PlanRecord`) |
| Authentification | **Traefik basicAuth** sur tout le site (`compose.custom.yaml`, `removeheader=true`). L'application ne sait pas qui appelle. Le service n'est pas publié (`expose` seulement) |
| Niveaux d'autonomie | `environments.yaml` : seulement `staging` (`default_level: 2`). Le niveau est figé dans le plan haché et recopié dans `executions.autonomy_level`, **sans CHECK** en base. La carte d'exécution affiche déjà le niveau (moitié du critère de #38) |
| Outils | `server.apply_playbook` et `server.healthcheck` : `environment: {enum: [staging]}`, avec le commentaire « production arrive avec R7 » |
| Skills | les trois sont en `status: draft`. Rien n'empêche aujourd'hui un plan de **production** de les citer (D13 de la spec non appliqué au plan) |
| `/healthz` | réponse typée `dict[str, str]` (OpenAPI : dictionnaire libre) |
| Restes ouverts | #105 et #127 (serveur, propriétaire) ; #32 (carte vue en ligne) ; #27 (attend `approval_required`) ; #31 (critère à aligner) ; #153 (plan S3) |

## Décisions à trancher (recommandation en premier)

| # | Question | Recommandation |
| --- | --- | --- |
| D1 | Source de l'identité en développement | **En-tête posé par Traefik** : `basicauth.headerfield=X-Forwarded-User`, que Traefik écrase. Variable `FOREMAN_AUTH_MODE` : `none` par défaut (poste et CI : utilisateur `dev` unique, rôle `developer`, l'en-tête est **ignoré**) ou `proxy_header` (en ligne : en-tête obligatoire, sinon 401). Rôles lus dans `FOREMAN_DEV_MEMBERS=nom:role,...` (`.env` du serveur, jamais dans le dépôt), synchronisés au démarrage dans `users` et `memberships`, avec un UUID déterministe (`uuid5`). OIDC reste en v1.1 (#85) ; une connexion propre à l'application (cookie, CSRF) coûterait plus |
| D2 | Où naît `approval_required` | **À la validation développeur** : la matrice est évaluée sur chaque étape du plan avec le rôle du demandeur. On réunit les `requires`, plus `admin_approved` si l'environnement l'exige. S'il manque `admin_approved`, on écrit l'approbation développeur sans créer d'exécution, on répond 202 `approval_required` et on émet la carte d'approbation. **La gateway refait le contrôle** (nouveau code `approval_required`). Pas d'état d'exécution `awaiting_approval` (choix de 0001 : l'attente est portée par le statut du plan) |
| D3 | Qui lance l'exécution après l'admin | **L'approbation admin crée l'exécution et démarre le moteur** (spec : un admin peut lancer). L'exécution est évaluée **avec le rôle du demandeur** (`plans.requested_by`) : R7 autorise `developer` dès que `plan_approved` et `admin_approved` sont satisfaits. L'agent n'obtient jamais plus que le demandeur (D2 de la spec) |
| D4 | Qui peut approuver, et comment le front le sait | Nouvelle section de la matrice : `approvers: {developer: [developer, team_admin, org_admin], admin: [team_admin, org_admin]}`. La carte d'approbation porte `approver_roles`, `GET /api/me` donne le rôle. Le bouton s'affiche si le rôle figure dans la liste : **le front ne contient aucune règle codée en dur** (#40). Le serveur refuse quand même (403 `forbidden`) |
| D5 | Forme des réponses | Route développeur inchangée pour 201 et 200, **plus un 202 `ApprovalPending`** (`{approval_id, status: "approval_required", missing: ["admin_approved"]}`). Nouvelle route `POST .../plans/{plan_id}/admin-approvals` (`{plan_hash, decision: approved\|rejected}`). `ApprovalAccepted` n'est pas modifié |
| D6 | Refus par l'admin | Ligne `approvals` avec `decision = rejected`. Le plan passe `invalidated` (premier état `invalidated` réellement écrit) et la carte d'approbation `rejected`. **P2 : c'est le premier élément qui glisse** |
| D7 | Écarts avec le YAML de la spec | R3 devient `allow_if [plan_approved]` (« dans le périmètre du plan approuvé »). R5 prend `class: write_registry` et `requires: [plan_approved, remediation_approved_by_admin]`. `never_autonomous` devient une **contrainte de validation** (règle `allow_if` avec `admin_approved`, jamais satisfaite par le niveau) et non un `Deny`. Écarts documentés dans le YAML |
| D8 | Autonomie en production | `environments.yaml` et `autonomy` de la matrice : `production {max_level: 3, admin_approval_required: true, default_level: 2}`. Le catalogue refuse au chargement `production` avec `max_level > 3`. **Migration 0003** : `executions.environment` (rempli depuis `plans.content`), `CHECK (autonomy_level BETWEEN 1 AND 4)` et `CHECK (environment <> 'production' OR autonomy_level <= 3)`. `org_ceiling` reste inutilisé (documenté) |
| D9 | Skills en brouillon et production (D13 de la spec) | `build_content` refuse un Skill `draft` hors `staging` (`invalid_plan`). L'enregistrement S10 ne cite **aucun** Skill. Publier un Skill est une décision humaine (les agents ne touchent pas `SKILL.md`) |
| D10 | `/healthz` | Contrat nommé `HealthResponse {status: "ok", profile: enum, version: str (motif, ≤ 32), persistence: "memory"\|"postgres"}`. Rien d'autre (pas le mode d'authentification) |
| D11 | Comment l'admin trouve la demande | En S4 : la carte d'approbation est dans le fil du projet et l'admin l'ouvre depuis la barre latérale. Liste des approbations en attente et notifications : #87 (v1.1) |
| D12 | Tickets anciens | #31 : aligner sur « S1 en mémoire et suite de contrat PostgreSQL », puis fermer (PR0). #153 : fermer avec PR0. #27 : fermer quand `approval_required` existe (PR-D) |

## Volet agentique

- **Matrice** (`catalog/policy/matrix.yaml`) : R1 à R10 dans l'ordre de la spec (spécifiques avant généraux), environnements `staging` et `production`, section `approvers`. Le `policy_sha256` de tous les plans change.
- **Référentiels** : `environments.yaml` gagne `production`. La question de clarification S2 propose donc `["staging", "production"]` : fixture S2 régénéré et assertion de `test_s02` mise à jour.
- **Outils** : `apply_playbook` et `healthcheck` acceptent `environment: [staging, production]`. Classes et réversibilités inchangées. `scope.py` est inchangé : les racines viennent déjà de `environments.yaml`.
- **Skills** : inchangés. Le refus des Skills `draft` hors staging est dans le planner (D9).
- **Provider** : nouvel enregistrement `catalog/recordings/s10.yaml`. Le message « Déploie Safe Eat en production » (sha256 exact) déclenche `propose_plan` avec `environment: production`, `bootstrap_project`, `deploy_compose` et `healthcheck`, sans Skill. Une seule entrée `default` (déjà contrôlé par `from_dir`).
- **Budgets** : inchangés.
- **Fakes** : aucun nouvel adaptateur. `SimulatedServer` accepte déjà tout environnement.
- **Outils du tour** : `propose_plan` et `ask_user` restent ouverts à tous les rôles (classe `control`, R2). Demander la production est permis ; c'est l'exécution qui est gardée.

## Volet back-end

**Contrat (additif, `v: 1`)**

- `CardData` gagne `ApprovalCardData{card_id, kind: "approval", plan_id, plan_hash, plan_card_id, environment, rule_id, missing: [Requirement], approver_roles: [Role], requested_by: {name}, status: pending|approved|rejected, decided_by?: {name}}`.
- `PlanCardData` gagne `admin_approval_required?: bool`.
- `ErrorCode` gagne `unauthenticated` (401), `forbidden` (403) et `policy_denied` (409 : une étape interdite au rôle, par exemple R8 pour un développeur).
- Routes : 202 sur `approvals` ; `admin-approvals` (501 jusqu'à PR-D) ; `GET /api/me` → `Me {user_id, name, role}` ; `HealthResponse`.

**Modules**

- `core/identity.py` (nouveau) : `Principal`, `Role`.
- `core/ports.py` : port `MemberStore` (`role_of`, `sync`).
- `core/store.py` : `NewPlan.requested_by` et `PlanRecord.requested_by` ; `PlanStore.approve(..., start_execution)`, `approve_admin`, `reject_admin` ; `ApprovalRefused` gagne `forbidden` et `policy_denied`.
- `core/policy/matrix.py` : correction de `never_autonomous` ; fonction pure `requirements(matrix, verdict, environment)`.
- `core/catalog.py` : `approvers`, garde sur `production`, validation de `never_autonomous`.
- `core/planning.py` : D9.
- `core/approval.py` : contrôle préalable (D2), carte d'approbation, service admin.
- `core/gateway/pipeline.py` : le rôle est relu à chaque appel depuis `plans.requested_by` (paramètre `role` du constructeur supprimé) ; `approval_required` ; accepte `admin_approved` ; l'audit renseigne `actor` = utilisateur demandeur.
- `core/gateway/errors.py` : nouveau code.
- `core/turn.py` : `TurnRequest.user_id: UUID`, transmis au planner.
- `infra/in_memory.py`, `infra/db/{plans,projects,tables}.py`, `infra/db/members.py` (nouveau).
- `bootstrap/configure.py` : mode d'authentification et synchronisation des membres.
- `config/env.py` : `FOREMAN_AUTH_MODE`, `FOREMAN_DEV_MEMBERS`.
- `surfaces/web/auth.py` (nouveau, dépendance FastAPI `current_principal`) ; `api.py` et `schemas.py` ; `app.py` (`HealthResponse`).

**Migration `0003_roles_autonomy`** (relecture propriétaire) : `memberships(user_id, team_id, role CHECK IN (developer, team_admin, org_admin), PK(user_id, team_id))`, `executions.environment` (rempli depuis les plans puis `NOT NULL`), deux CHECK. `downgrade` est permis : il ne détruit pas l'audit.

**Sécurité**

- En mode `none`, l'en-tête `X-Forwarded-User` est **ignoré**.
- En mode `proxy_header`, un en-tête absent ou un utilisateur inconnu donne 401 opaque, sans écho du nom.
- Un rôle insuffisant donne 403, et rien n'est écrit.
- `requested_by` vient du serveur, jamais du corps de la requête.
- Les erreurs restent opaques ; aucun appel bloquant.

**Tests (1 à 3 par PR)**

- Une table paramétrée rôle × niveau × environnement × classe (R1 à R10, `approval_required`, refus par défaut, `never_autonomous`).
- Le catalogue refuse `production` avec `max_level: 4`.
- La migration refuse une exécution de production au niveau 4 (vrai PostgreSQL).
- Authentification : 401 sans en-tête en `proxy_header` ; en-tête ignoré en `none`.
- Gateway : plan de production `dev_approved` sans admin → `CallDenied("approval_required")`, adaptateur non appelé, ligne d'audit `denied` avec R7.
- Contrat des dépôts (mémoire et PostgreSQL) : `approve_admin` idempotent, développeur → `forbidden`.
- e2e S10.

## Volet front-end (DESIGN.md d'abord)

- **DESIGN.md**, nouvelle section « Carte d'approbation (Semaine 4) » :
  - `Card` avec `CardHeading` (icône `ShieldCheckIcon`, titre « Approbation administrateur », description « Ce plan vise la production : un administrateur doit l'approuver. »).
  - `FactList` : environnement, demandé par, règle, empreinte courte.
  - Si le rôle figure dans `approver_roles` et que la demande est `pending` : **« Approuver »** (par défaut, un clic) et **« Refuser »** (`outline`).
  - Sinon : ligne `role="status"` « En attente d'un administrateur ». États approuvé et refusé : ligne de statut. Erreurs dans une `Alert` en français ; sur 409 ou 404, on attend la carte réémise.
- **PlanCard** : si `admin_approval_required`, le libellé devient « Valider et transmettre à l'admin ». Sur 202 : « Validé. En attente d'un administrateur. »
- **`useMe`** (`GET /api/me`) ; **`useAdminApproval`** ; `api/client.ts` gère 202 et `forbidden`. Types régénérés (`make api-types`), dont `HealthResponse` pour `useHealth`.
- Badge nom et rôle en pied de barre latérale : P2.
- **Test de rendu léger** sur `s10-events.json` : en `developer`, aucun bouton « Approuver » ; en `team_admin`, les deux boutons. Le rôle passe par la réponse simulée de `/api/me`, pas par une règle du front.

## Pile de PR empilées (deux pistes : back séquentiel, front dès que le contrat est fusionné)

| PR | Branche (base) | Contenu | Ticket | Prio | Taille | Critère de fin observable |
| --- | --- | --- | --- | --- | --- | --- |
| PR0 | `docs/plan-semaine-4` (prod) | Ce plan ; ROADMAP (S3 terminé, S4 en cours) ; alignement de #31, #36, #37 et #39 (`## Critère de fin` au format standard ; « revue propriétaire » au lieu de CODEOWNERS) | à créer | P0 | petite | Plan fusionné ; #31 et #153 fermés |
| PR-A | `feat/contract-s4` (prod) | Carte d'approbation, `admin_approval_required`, codes 401/403/`policy_denied`, 202 `ApprovalPending`, route `admin-approvals` en 501, `GET /api/me` (identité de dev), `HealthResponse`, types TS | à créer | P0 | petite | Contrôle de dérive OpenAPI vert ; `/healthz` typé en objet dans `openapi.json` |
| PR-B | `feat/policy-matrix` (prod, en parallèle de PR-A : ne touche pas le contrat) | R1 à R10, `approvers`, production (matrice, référentiel, enums d'outils), correction de `never_autonomous`, `requirements()`, garde production ≤ 3, D9, fixtures S1 et S2 régénérés | #36, #38 (moitié) | P0 | moyenne | Table de cas verte ; catalogue refusé avec production au niveau 4 ; `test_s01` et `test_s02` verts |
| PR-C | `feat/dev-auth-roles` (PR-A) | 0003, `MemberStore`, `FOREMAN_AUTH_MODE`, `FOREMAN_DEV_MEMBERS`, `current_principal`, `/api/me` réel, `requested_by`, label Traefik `headerfield`, `DEPLOYMENT.md` et `PERSISTENCE.md` | #37, #38 (moitié) | P0 | moyenne à grosse | 401 sans identité en `proxy_header` ; en-tête ignoré en `none` ; CHECK production ≤ 3 vert sur PostgreSQL |
| PR-D | `feat/admin-approval` (PR-B + PR-C) | Rôle relu par la gateway, `approval_required`, contrôle préalable, carte d'approbation, `approve_admin` et `reject_admin` (mémoire et PostgreSQL), route réelle | #36 (fin), #39, #27 | P1 | grosse | Contrôle de la gateway vert (adaptateur non appelé, audit R7) ; contrat des dépôts vert ; #27 fermé |
| PR-E | `test/s10-production` (PR-D) | `s10.yaml`, `s10_run.py`, `test_s10_production_sans_droit.py`, `make s10-fixture`, `s10-events.json` | #39 | P1 | moyenne | `test_s10_production_sans_droit.py` vert en CI |
| PR-F | `feat/front-approval-card` (PR-A, puis le fixture de PR-E) | DESIGN.md, `ApprovalCard`, `useMe`, `useAdminApproval`, libellé de PlanCard, test de rendu | #40 | P1 | moyenne | Carte rendue depuis `s10-events.json` : pas de bouton pour `developer`, boutons pour `team_admin` |
| PR-G | `chore/s3-followups` (prod) | Suivi de la revue de PR-A (S3) : test d'ordre qui échoue sans le verrou, test de rétention sur PostgreSQL, `at` indépendant du fuseau de la base | à créer | P2 | petite | Les trois tests sont verts ; le test d'ordre échoue si on retire le verrou (vérifié et noté dans la PR) |

**Scénario S10** (déroulé dans PR-E, en mode `proxy_header`, membres fictifs `dev:developer` et `admin:team_admin`) :

1. `dev` envoie le message ; la carte plan affiche `production`, niveau 2, `approvable` et `admin_approval_required`.
2. `dev` valide : réponse 202 `approval_required`. Aucune exécution en base, plan `dev_approved`, carte d'approbation `pending` avec R7.
3. `dev` appelle `admin-approvals` : 403, rien n'est écrit.
4. `admin` approuve : 201, exécution `succeeded` au niveau 2, audit `allow` R7 avec comme acteur le **demandeur**, carte d'approbation `approved`.
5. Les `seq` sont contigus et aucun secret n'apparaît.

**Réaliste pour la semaine** : PR0, PR-A, PR-B, PR-C et PR-D, puis PR-E.

**Ce qui glisse, dans l'ordre** :

1. PR-G ;
2. le refus admin (D6) et le bouton « Refuser » ;
3. le badge de rôle dans la barre latérale ;
4. le contrôle « ses projets » pour la validation développeur ;
5. PR-F, qui passe en S5.

S10 n'est **fini** (règle de `CLAUDE.md`) qu'avec PR-F. Si elle glisse, le jalon reste ouvert.

## Impact sur les contrats figés

**Tout est additif, aucun passage en v2** : nouveau `kind` de carte, champ facultatif sur la carte plan, nouveaux codes d'erreur (même pratique que `question_closed` en S3), nouveau code 202, nouvelles routes, `/healthz` décrit en objet au lieu d'un dictionnaire.

**Changements de comportement** à signaler dans les PR :

- `approvable` vaut vrai pour un plan de production (il valait faux) ;
- en `proxy_header`, une requête sans identité reçoit 401 ;
- la gateway répond `approval_required` au lieu de `policy_denied` quand l'environnement exige un admin (`test_gateway` est mis à jour) ;
- la clarification S2 propose aussi `production` ;
- un plan qui cite un Skill `draft` hors staging est refusé.

## Risques

- **Usurpation d'en-tête** si l'application est joignable sans passer par Traefik. Aujourd'hui elle ne l'est pas (`expose` seulement). Le mode `none` ignore l'en-tête. Il faut vérifier sur le serveur que Traefik **écrase** un `X-Forwarded-User` envoyé par le client. `compose.yaml` (proxy sans basicAuth) reste en `none`.
- Le changement de matrice et de référentiel change tous les hash : les fixtures S1 et S2 sont à régénérer, sinon les tests passent au rouge.
- PR-D est la plus grosse (gateway, approbation, deux dépôts). Si elle glisse, PR-B et PR-C livrent quand même la matrice complète, les rôles et l'autonomie.
- Si le plan expire (24 h) entre la validation développeur et l'approbation admin : 409 et carte réémise. L'état `expired` n'est toujours pas écrit en base : c'est S12 (#43).
- Une ressource `server_project` est identifiée par le slug **seul** : un projet de staging au registre satisferait la portée `update` d'un déploiement de production. Dans S10, le projet est neuf, donc sans effet ici ; ticket à créer.
- Une seule équipe : un `team_admin` voit et approuve tous les projets (limite du PoC, documentée).
- `memberships` est synchronisé depuis l'environnement à chaque démarrage : retirer un nom retire son rôle (la synchronisation remplace, elle n'ajoute pas seulement).
- Restes acceptés : formes non masquées par `redact.py` (S7, #57), messages en clair en base (#64).

## Côté serveur (propriétaire)

1. Dans `/opt/foreman/.env` : `FOREMAN_AUTH_MODE=proxy_header` et `FOREMAN_DEV_MEMBERS=<nom>:developer,<nom>:team_admin`. Les noms sont ceux de `FOREMAN_BASIC_AUTH_USERS`. Recopier `compose.custom.yaml` (label `headerfield`).
2. Un `pg_dump` est fait avant le déploiement (0003). Relire 0003 et `surfaces/web/auth.py`.
3. `curl -u <dev>:… https://<domaine>/api/me` doit renvoyer `developer`. `curl -u <dev>:… -H 'X-Forwarded-User: <admin>' …/api/me` doit renvoyer **encore** `developer` : c'est le contrôle de sécurité clé.
4. `curl https://<domaine>/healthz` doit renvoyer la forme fermée, avec `persistence: postgres`.
5. Fermer #127, #105 et #32 avec une capture (chat intact après redéploiement, flux SSE, cartes visibles).

## Tickets à créer ou corriger (jalon « PoC S4 », label de priorité, `## Critère de fin`)

- **À créer** :
  - Plan S4 (PR0, P0) ;
  - Contrat S4 (PR-A, P0, avec `HealthResponse`) ;
  - Suivi de la revue du journal (PR-G, P2, `area:migrations`) ;
  - `server_project` identifié par environnement et slug (P2, jalon S5) ;
  - Formes non masquées par `redact.py` (P3, lié à #57) ;
  - Décision D1, mode d'authentification (`type:decision`, P1).
- **À corriger** :
  - #37 et #39 : remplacer « **Fin :** » par un `## Critère de fin` observable (#37 : « 401 sans identité, rôle relu à chaque appel de la gateway, test vert » ; #39 : inchangé sur le fond) ;
  - #36 : retirer « Revue propriétaire faite » au profit de « relecture propriétaire », ajouter `never_autonomous` ;
  - #38 : préciser que le CHECK porte sur `executions(environment, autonomy_level)` ;
  - #27 : sera fermé par PR-D ;
  - #31 et #153 : seront fermés par PR0.
