# Plan — Semaine 2 : scénario S1 (chemin nominal sur adaptateurs simulés)

Établi par un agent Opus d'après le code de `prod` (commit `c890f10`), contrôlé par un sous-agent Haiku sur les
tickets du jalon 2, exécuté par Sonnet. Même méthode que `semaine-1.md`.

**Objectif.** Un développeur décrit un projet dans le chat ; l'agent (modèle **rejoué**, pas de vrai modèle)
produit un plan **haché** ; le développeur le **valide** (l'approbation porte sur le hash) ; le moteur
l'exécute étape par étape **uniquement via la Tool Gateway**, sur des adaptateurs **simulés** (faux GitLab, faux
serveur, faux DNS) ; le registre des ressources et l'audit se remplissent ; un health check simulé conclut.
**Fin :** le scénario S1 passe en CI avec un vrai PostgreSQL, et les cartes plan et exécution sont affichées.

Hors semaine : S2 à S12, matrice R1 à R10, rôles et authentification (S10), `set_variable` et secrets réels,
fournisseurs réels, `environments`, `servers`, `connectors`, `permission_requests`, `skill_versions`.

## Hypothèses retenues

1. Les événements du chat restent **en mémoire** ; **projets, plans, approbations, exécutions, étapes, registre
   et audit** passent en PostgreSQL (un plan en base ne doit pas pointer vers un projet perdu au redémarrage).
2. En staging le développeur valide seul son plan (pas de validation admin, pas de rôles).
3. Référentiels et Skills à valeurs **fictives** (convention GitLab réelle : #65).
4. SQLAlchemy 2 **Core** (pas l'ORM, pour garder le SQL de la spec lisible), psycopg 3 asynchrone, Alembic.
5. Matrice **minimale** : R1, R2, R6, refus par défaut.
6. Idempotence et bail **structurels** (contraintes d'unicité, clé d'idempotence, bail) ; les scénarios S11 et S12
   sont les semaines 5 et 6.
7. Aucun chemin d'échec (S3 à S9) ; une exception inattendue finit l'exécution en `blocked`.

## Décisions de conception

**11 tables** migrées : `users`, `teams` (minimales, insérées au démarrage), `projects`, `plans`, `approvals`,
`executions`, `execution_steps`, **`step_idempotency`** (nouvelle, absente de la spec), `managed_resources`,
`observed_state`, `audit_events` (avec son trigger). Repoussées : `memberships`, `connectors`,
`permission_requests`, `servers`, `environments`, `project_specs`, `project_messages`, `skill_versions`.

**Défauts du SQL de la spec** (jamais exécuté) corrigés dans la migration :
1. `projects.slug` nullable (un projet est créé sans titre) ; le plan fixe le slug.
2. `approvals.plan_hash` doit égaler `plans.content_hash` : `UNIQUE(id, content_hash)` sur `plans` et clé
   étrangère composite `(plan_id, plan_hash)`, plus un index unique partiel `(plan_id, kind) WHERE decision='approved'`.
3. `executions` : `UNIQUE(plan_id)`, colonne `project_id`, index unique partiel
   `(project_id) WHERE state IN ('running','awaiting_permission','awaiting_remediation')`. Pas d'état
   `awaiting_approval` dans le `CHECK` (l'attente est portée par le plan). Isolation entre projets :
   `UNIQUE(id, project_id)` sur `plans` et clé étrangère composite `(plan_id, project_id)` sur `executions`.
4. `execution_steps.idempotency_key` n'est plus unique : les étapes sont pré-insérées en `pending`
   (`UNIQUE(execution_id, seq)`) et la réservation passe par `step_idempotency(key PK, step_id, result)` avec
   `INSERT … ON CONFLICT DO NOTHING RETURNING`. Portée de la clé : `PRIMARY KEY (project_id, key)` (jamais
   globale) et colonne `status` (`reserved` | `succeeded` | `failed`) pour distinguer réservé et terminé.
5. `audit_events` : trigger `BEFORE UPDATE/DELETE` (par ligne) et trigger **distinct** `BEFORE TRUNCATE`
   (`FOR EACH STATEMENT`, seule forme valide pour `TRUNCATE`) ; colonnes `project_id`, `plan_id`,
   `step_seq`, `plan_hash`, `actor` ; pas de clé étrangère sur `execution_id`. Limite documentée : le rôle de
   l'application possède la table et peut supprimer le trigger (rôles séparés en v1.0).
6. `observed_state` : ajout de `id bigserial` (pas de clé primaire dans la spec).
7. Bail : colonne `lease_epoch` incrémentée à chaque prise ; toute écriture d'une étape vérifie l'époque (un
   travailleur dont le bail a expiré ne peut plus écrire). Pas d'état « en file » : `running` avec bail nul ou expiré = à prendre. L'attente d'approbation est portée par
   `plans.status = 'proposed'`.
8. `plans.expires_at` : `created_at + 24 h` (fixe cette semaine).
9. États en anglais partout (base, API, événements).
10. Les Skills sont tracées par `sha256` du contenu (le conteneur n'a pas de `.git`).
11. Marquage du registre : `managed-by=foreman` (la spec dit `devplatform`).

**Plan haché.** Contenu canonique `PlanContent` (Pydantic, `extra="forbid"`) : `schema, project_id, version, title,
summary, environment, autonomy_level, stack, steps[{seq, title, tool, tool_version, tool_class, reversibility,
params, idempotency_key}], expected_resources, skills[{name, version, status, sha256}], referentials, policy_sha256`.
JSON trié, séparateurs compacts, `ensure_ascii=False`, flottants et NaN refusés ; `"sha256:" + hex`. Hors du hash :
`id`, `expires_at`, `status`. La classe, la réversibilité et les clés viennent du **catalogue**, jamais du modèle.

**États.** Plan : `proposed → dev_approved → executed`. Exécution : `running → succeeded | blocked`.

**Moteur.** `ExecutionWorker` (tâche asyncio du même processus), bail 60 s renouvelé, point de reprise = première
étape non réussie. Le moteur ne connaît que le port `Gateway`.

**Gateway (10 étapes).** Faites cette semaine : contexte, droits (matrice minimale), schéma (jsonschema, le chargeur
refuse un outil sans `additionalProperties: false`), périmètre (création : parent dans le registre ou racine
autorisée), approbations (plan `dev_approved`, hash égal, **appel identique à l'étape `seq` du plan**), budget
(appels et durée), exécution avec délai, sortie (champs `redact`, secrets masqués, troncature 4 Kio / 50 lignes),
journal (chaque décision). No-op documentés : essais par étape et coût du modèle, injection de secret.

**Outils et fakes.** `gitlab.create_group`, `gitlab.create_project`, `server.apply_playbook`
(`bootstrap_project`, `deploy_compose`), `server.healthcheck`, `dns.list_records` ; `SimulatedGitLab`,
`SimulatedServer`, `SimulatedDns` (état inspectable par les tests). Plan S1 : 7 étapes puis un health check.

**Skills et référentiels.** `catalog/skills/<nom>/SKILL.md`, `catalog/referentiels/*.yaml`,
`catalog/policy/matrix.yaml`, `catalog/recordings/s01.yaml` (modèle rejoué, choisi par hash du dernier message, sans
état). Un brouillon est refusé hors staging. `yaml.safe_load` partout.

## Contrat additif (`v: 1`) — livré par la PR P1

| Méthode | Chemin | Corps | Réponses |
| --- | --- | --- | --- |
| POST | `/api/projects/{id}/plans/{plan_id}/approvals` | `{"plan_hash": "sha256:<64 hex>", "decision": "approved"}` | 201 `{approval_id, execution_id}` (création) ; **200 mêmes identifiants** (rejeu idempotent, même hash sur un plan déjà `dev_approved`) ; 404 (aussi pour une ressource d'un autre projet) ; 422 ; 409 `plan_hash_mismatch` (hash différent) / `plan_not_approvable` (expiré, invalidé, exécuté) / `execution_in_progress` |
| GET | `/api/projects/{id}/plans/{plan_id}` | – | 200 `PlanView` ; 404 |
| GET | `/api/projects/{id}/executions/{execution_id}` | – | 200 `ExecutionView` ; 404 |

**Événements.**
- `card` : `CardEvent.data` devient une **union discriminée sur `kind`** (`plan` | `execution`), `kind` requis dans le schéma.
- `PlanCardData` gagne des champs **facultatifs** : `plan_id, plan_hash, status, environment, autonomy_level, stack,
  skills, expected_resources, approvable` ; `CardStep` gagne `tool, tool_class, reversibility`.
- Nouvelle carte `kind: "execution"` : `execution_id, plan_card_id, state, autonomy_level, steps, budget, resources,
  result{summary, links}`. Réémise **entière** (remplacement par `card_id`) à chaque changement.
- Nouveau type `execution_log` : `{card_id, step, lines[≤50 de ≤500 caractères]}`, toujours filtré par la gateway.
- `ErrorData.code` gagne `invalid_plan`.

**Approbation atomique.** Insertion de l'approbation, passage du plan à `dev_approved` et création de l'exécution
se font dans **une seule transaction** ; un double clic ne crée donc jamais deux exécutions.

**Ordre des événements.** Après approbation, la carte plan est **réémise** (`status: dev_approved`,
`approvable: false`) *avant* la carte d'exécution ; la carte d'exécution précède tout `execution_step` et
`execution_log` de même `card_id` ; ces deux types visent la carte d'**exécution**. Sur un 409, le front attend
la carte plan réémise plutôt que de deviner l'état. Un événement dont la carte est inconnue est ignoré.

**Vocabulaires et formats.** Un seul `PlanStatus` à six valeurs (carte plan et `PlanView`). Tous les hachages
valent `sha256:<64 hex>` (y compris `skills[].sha256`). `ExecutionStepView.step` et `ExecutionView.budget` suivent
les noms des événements ; `ExecutionView` porte `plan_card_id` et `result`. Les clients **ignorent les champs
inconnus**. `stack` est borné (≤10 clés `[a-z][a-z0-9-]*`, valeurs ≤100 caractères).

**Précisions.** Le serveur sérialise aussi les champs vides (`null`) : côté TypeScript ils sont **présents et
nullables**. Les liens (`url`) sont limités à `http(s)` : jamais `javascript:`. `ExecutionState` contient dès
maintenant **tous** les états de la spec (en ajouter plus tard casserait un client strict). Un front ancien affiche
« Carte non prise en charge » et ignore `execution_log` : le changement est additif.

## PR empilées

Deux pistes au plus : le back en série (P2 à P8) et le front (P9), toutes deux sur le contrat P1.

**Livrable A — fondations de persistance (P1 à P3).** Critère : migrations vertes sur un vrai PostgreSQL en CI, et
un projet créé en staging survit à un redéploiement. **Livrable B — gateway, moteur et scénario (P4 à P9).**

| PR | Branche | Contenu | Tickets | Dépend de |
| --- | --- | --- | --- | --- |
| P1 | `feat/contract-s1` | ce plan, événements et schémas additifs, routes en 501, `openapi.json`, types | #124 | – |
| P2 | `feat/db-migrations` | dépendances, Alembic, verrou, `tables.py`, service PostgreSQL en CI | #25 | P1 |
| P3 | `feat/persistence-stores` | ports, dépôts PostgreSQL et mémoire (suite de contrat commune), `--with-db` dans `deploy.yml` | #26, #126, #127 | P2 |
| P4 | `feat/catalog-skills` | `catalog/`, chargeur, YAML d'outils | #30, #128 | P3 |
| P5 | `feat/simulated-adapters-replay` | fakes, `ReplayProvider`, suppression de `ScriptedProvider` | #29 | P4 |
| P6 | `feat/gateway-minimal` | pipeline, matrice, masquage, audit | #27 | P5 |
| P7 | `feat/execution-engine` | planning et hash, approbation, worker, routes réelles | #28, #125 | P6 |
| P8 | `test/s01-nominal` | `tests/e2e/test_s01_nominal.py`, export du fixture front | #31 | P7 |
| P9 | `feat/front-plan-card`, `feat/front-execution-card` | carte plan et bouton **Valider**, carte d'exécution et logs | #32 | P1, puis fixture de P8 |

## Tests et sécurité

**Cas.** Migrations (vide, double exécution, deux `upgrade` concurrents, downgrade puis upgrade, `UPDATE`/`DELETE`/
`TRUNCATE` refusés) ; dépôts (même suite sur mémoire et PostgreSQL) ; planning (hash stable, sensible aux titres,
aux paramètres et aux Skills) ; gateway (permis, refusé par défaut, hors registre, hors plan, hash différent, budget,
masquage) ; moteur (concurrence, reprise, exception inattendue) ; API (approbation, erreurs opaques) ; S1 de bout en
bout. **Mutations** à vérifier : retirer la comparaison du hash, `ON CONFLICT`, la clause `WHERE` du bail,
`additionalProperties`, le trigger, la comparaison de l'appel à l'étape, le masquage, l'audit d'un refus.

**Sécurité.** La gateway est le seul chemin (le moteur ne reçoit que le port ; import-linter interdit
`core → integrations`) ; `docs/DEBT.md` reste vide ; l'URL de la base n'apparaît dans aucun log ; Alembic tourne dans
`asyncio.to_thread` ; contenus bornés (20 étapes, 64 Kio par plan).

## Risques et décisions du propriétaire

- Volume de la semaine : le livrable A sécurise la persistance même si B glisse.
- Rôle PostgreSQL propriétaire de l'audit : le trigger est contournable (rôles séparés en v1.0).
- Le replay `default` répond S1 à toute demande en staging (démonstration assumée).
- Les identifiants du replay S1 sont **littéraux** : les sous-groupes visent les groupes `2000`, `2001` et `2002`,
  que `SimulatedGitLab` produit dans l'ordre. P6 (gateway) doit donc filtrer le registre par `project_id` (deux
  projets ne partagent pas leurs ressources), et P7 (planning) prévoira des références aux sorties d'étapes
  (par exemple `{{steps.1.group_id}}`) au lieu d'identifiants écrits en dur.
- `apply_playbook` : la réversibilité et la portée viennent du playbook (`playbooks` dans la définition) ; la gateway
  doit imposer `params.environment == plan.environment`, et le fake GitLab n'adopte jamais une ressource sans le
  marquage `managed-by=foreman` (`ForeignResource`).
- Au redémarrage le chat est vidé alors que plans et exécutions restent en base ; il n'y a pas de route de liste :
  le front retrouve un plan ou une exécution par identifiant (portés par les cartes).
- À trancher : (1) valider ce contrat additif ; (2) valider les ajustements du schéma ci-dessus ; (3) migrations au
  démarrage de l'application ou commande dédiée ; (4) marquage `managed-by=foreman` ; (5) `POSTGRES_PASSWORD` et
  `FOREMAN_DATABASE_URL` dans `/opt/foreman/.env` ; (6) #64 (ADR modèle et logs bruts) : ne bloque pas la semaine.
