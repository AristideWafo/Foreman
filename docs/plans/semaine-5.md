# Plan — Semaine 5 : scénario S11 (même demande rejouée, aucune ressource en double)

Plan écrit par l'agent `Plan` (Opus) d'après l'état réel de `prod` (après #183). Les tests back sont unitaires : 1 à 3 par fonctionnalité, seulement les plus utiles. `gateway/` et `migrations/` gardent une relecture attentive du propriétaire.

## État de départ (vérifié dans le code)

| Élément | État |
| --- | --- |
| Clés par étape (`core/planning.py`, `build_content`) | Le gabarit vient du YAML de l'outil. Les clés GitLab sont **au niveau du projet** (`{project_id}:gitlab.group:{parent}:{path}`). Une clé qui contient un `$from` reçoit le préfixe `{execution_id}`. `apply_playbook` utilise `{execution_id}:{step_seq}:{playbook}` |
| Réservation (`step_idempotency`, PK `(project_id, key)`) | `reserve_idempotency` renvoie `New`, `Completed` (le moteur reprend le résultat et écrit l'audit `replayed`) ou `Orphan` (l'exécution passe `blocked`, sans rappel) |
| Registre (`managed_resources`) | Contrainte `UNIQUE(provider, resource_type, external_id)`, globale, lignes supprimées comprises. La gateway refuse `foreign_resource` quand la ressource appartient à un autre projet (`exists_elsewhere`) |
| Unicités déjà en base | `executions.plan_id`, une seule exécution active par projet, `execution_steps(execution_id, seq)`, `approvals(plan_id, kind)`, `plans(project_id, version)`, `project_events(project_id, seq)`. Le rejeu des routes d'approbation (développeur et admin) est idempotent et répond 200 |
| Adaptateurs simulés | « lire puis créer » pour GitLab ; le serveur rejoue le même résultat pour une même clé. Leur état vit **en mémoire** : #183 donne des bases aléatoires pour les identifiants, mais le faux oublie tout au redémarrage |

## Trous d'idempotence trouvés (ce que S11 doit couvrir)

1. **Trou 1 (P0) : rejouer la même demande bloque l'exécution.** Le deuxième plan d'un même projet a le même contenu et le même hash, avec un autre id. Son étape 1 est reprise grâce à la clé du projet. Les étapes 2 à 5 (clés préfixées par `$from`) rappellent l'adaptateur, qui retrouve la ressource existante et renvoie le même id. `_resources` la déclare alors comme créée, `complete_step` lève `DuplicateResource` et l'exécution finit `blocked`. Même chose à l'étape 6 (`bootstrap_project`, slug déjà au registre). Cause : `AdapterResult` ne dit pas si la ressource a été **créée** ou **trouvée**.
2. **Trou 2 (P1) : après un échec, une réservation orpheline bloque le projet pour toujours.** Un échec d'adaptateur laisse la clé `reserved`, et `finish(blocked)` ne la libère pas. Si l'étape était un `create_group` racine (clé au niveau du projet), tout nouveau plan identique tombe sur `OrphanReservation` et finit `blocked`. Rejouer après un échec est donc impossible.
3. **Trou 3 (P2, #177) :** `server_project` est identifié par le slug seul. Un projet de staging satisfait alors la portée `update` d'un déploiement de production, et sa ligne de registre entrerait en conflit avec celle d'un projet de production du même nom.
4. **Trou 4 (P1) : la carte d'exécution rejouée est vide.** `execution_card` ne liste que les ressources dont `execution_id` est celui de l'exécution courante. Au rejeu, elle n'affiche aucune ressource et aucun lien : l'utilisateur ne voit pas qu'elles étaient déjà là.
5. **Trou 5 (test) : redémarrage avec PostgreSQL.** Le faux GitLab oublie ses groupes, alors que le registre et `step_idempotency` les gardent. Un vrai GitLab est durable : le test de redémarrage **garde la même instance d'adaptateurs** entre deux `configure` (le faux tient le rôle du fournisseur durable). Les bases aléatoires de #183 restent pour le serveur réel.

## Décisions à trancher (recommandation en premier)

| # | Question | Recommandation |
| --- | --- | --- |
| D1 | Comment l'adaptateur signale « déjà présent » | `AdapterResult.created: bool \| None` (port `core/ports.py`). Pour un outil `write_registry` de portée `create` qui n'est pas en mode `check`, `None` donne `invalid_output` : un adaptateur doit le dire |
| D2 | Ce que fait la gateway avec une ressource trouvée | Si elle est au registre **de ce projet** : on la réutilise, aucune `NewResource`, audit `executed` avec `reused: true` dans le résultat masqué. Si elle est dans un autre projet : `foreign_resource` (inchangé). Si elle est marquée « gérée par Foreman » mais absente de tout registre : `foreign_resource` (l'adoption demande un admin, R4 et R5). On n'utilise **jamais** `ON CONFLICT DO NOTHING` dans `complete_step` : l'unicité en base reste le dernier filet |
| D3 | Réservation orpheline | Reprise permise si l'outil est de classe `read` ou déclare `idempotency.strategy` ou `on_conflict` (catalogue). Nouvelle méthode `ExecutionStore.take_over(lease, seq)` : elle rattache la clé `reserved` à l'étape courante, dans une transaction. Les autres cas restent `blocked`. Un refus de la gateway **avant effet** (`CallDenied`) libère la réservation |
| D4 | Identité `server_project` (#177) | Le YAML porte `registry.external_id: "{input.environment}/{input.project}"`, utilisé par `_resources` et par la portée `update`. **Migration 0004** : réécrit les lignes existantes depuis `executions.environment`. L'unicité globale ne change pas (l'unicité partielle `deleted_at IS NULL` attend UC15) |
| D5 | Deux POST `/messages` identiques | Deux tours et deux plans de même hash : c'est voulu (chaque plan est versionné). L'en-tête HTTP `Idempotency-Key` sur `/projects` et `/messages` sort du périmètre (P3, ticket). L'idempotence est garantie à l'exécution, pas au tour |

## Volet agentique

- **Skills et prompt** : inchangés.
- **Outils** : `apply_playbook.yaml` et `healthcheck.yaml` portent l'identité composée (D4) ; classes et réversibilités inchangées.
- **Matrice et budgets** : inchangés.
- **`Provider`** : aucun nouvel enregistrement. S11 **rejoue `s01.yaml`** (même message, donc même réponse et même hash de plan) : c'est exactement « la même demande ».
- **Fakes** : `SimulatedGitLab` et `SimulatedServer` renseignent `created` ; le serveur rend `created=False` si le projet est déjà préparé. Pas de nouvel adaptateur.

## Volet back-end

- **Contrat (additif, `v: 1`)** : `ResourceRef.reused?: bool`. Pas de nouveau code d'erreur, pas de nouvelle route. `make api-types`.
- **Modules** :
  - `core/ports.py` : `created`.
  - `core/gateway/pipeline.py` : D1 et D2, identité composée.
  - `core/gateway/scope.py` : cible `update` composée.
  - `core/catalog.py` : gabarit de `external_id`.
  - `core/store.py` : `take_over`, `TakenOverReservation`.
  - `core/execution/engine.py` : D3, libération sur `CallDenied`.
  - `core/execution/cards.py` : ressources lues depuis les **résultats des étapes** réussies, `reused` si `execution_id` diffère, résumé « N ressources déjà présentes, aucune créée ».
  - `infra/in_memory.py` et `infra/db/executions.py` : `take_over`.
  - `integrations/*/simulated.py`.
- **Migration `0004_server_project_identity`** (relecture propriétaire) : `UPDATE managed_resources ... FROM executions` pour `server_project` ; `downgrade` inverse. Faire un `pg_dump` avant le déploiement.
- **Sécurité** : erreurs opaques (`reused` n'expose aucun identifiant brut au-delà de `ResourceRef`) ; registre toujours cloisonné par projet ; aucune écriture hors registre ; aucun appel bloquant.

## Volet front-end

- **DESIGN.md** : section « Ressources déjà présentes (Semaine 5) ». `ResourceList` affiche un `Badge` `secondary` « déjà présente » si `reused`. `ExecutionCard` affiche le résumé du serveur tel quel ; le front n'applique aucune règle.
- **Types** régénérés ; fixture `s11-events.json` (`make s11-fixture`).
- **Test de rendu léger** : la deuxième carte d'exécution de `s11-events.json` affiche 6 badges « déjà présente » et 8/8 étapes réussies.
- **Badge nom et rôle** dans la barre latérale (reste S4, P2) : `useMe` existe déjà.

## Scénario S11 (`tests/e2e/s11_run.py`, en mémoire)

1. Projet « Safe Eat », message S1, validation, exécution `succeeded`. On relève le registre (6 lignes) et les faux (3 groupes et 2 dépôts gérés, 1 projet serveur).
2. **Même message**, deuxième plan : même `plan_hash`, autre `plan_id`. Validation, exécution `succeeded` (pas `blocked`).
3. Registre **identique** (mêmes 6 `external_id`, aucune nouvelle ligne) et faux inchangés. Audit : `replayed` à l'étape 1, `executed` avec `reused` aux étapes 2 à 6.
4. Carte 2 : 8/8 étapes, 6 ressources `reused`. `seq` contigus, aucun secret.
5. **Variante PostgreSQL** (`tests/db/test_s11_restart.py`) : étapes 1 à 4 avec un redémarrage entre 1 et 2 (nouvelle `App`, même base, mêmes adaptateurs).

## Pile de PR (deux pistes : back en série, front dès PR-A fusionnée)

| PR | Branche (base) | Contenu | Ticket | Prio | Taille | Critère de fin observable |
| --- | --- | --- | --- | --- | --- | --- |
| PR0 | `docs/plan-semaine-5` (prod) | Ce plan ; ROADMAP (S5 en cours) ; `## Critère de fin` de #41 et #42 ; tickets ci-dessous | à créer | P0 | petite | Plan fusionné, #41 et #42 au format standard |
| PR-A | `feat/contract-s11` (prod) | `ResourceRef.reused`, `openapi.json`, types TS | à créer | P0 | petite | Contrôle de dérive OpenAPI vert |
| PR-B | `feat/registry-reuse` (PR-A) | D1, D2, carte (trou 4), fakes | #41 | P0 | moyenne | Test de gateway : une ressource trouvée au registre du projet n'est pas réinscrite, une ressource trouvée hors registre donne `foreign_resource` |
| PR-C | `feat/orphan-takeover` (PR-B) | D3 (`take_over` en mémoire et sur PostgreSQL) | à créer | P1 | moyenne | Contrat des dépôts : après un échec à l'étape 1, un plan identique réussit sans doublon (deux backends) |
| PR-D | `feat/server-project-identity` (PR-B) | D4, migration 0004 | #177 | P2 | petite à moyenne | Test #177 vert ; 0004 réécrit une ligne existante (vrai PostgreSQL) |
| PR-E | `test/s11-rejeu` (PR-C) | `s11_run.py`, `test_s11_rejeu.py`, `test_s11_restart.py`, `make s11-fixture` | #42 | P1 | moyenne | Les deux tests sont verts en CI |
| PR-F | `feat/front-s11-card` (PR-A, puis le fixture de PR-E) | DESIGN.md, badge, test de rendu | #42 (carte) | P1 | petite | Carte rendue depuis `s11-events.json` avec 6 « déjà présente » |
| PR-G | `chore/s3-followups` (prod) | Reste S4 (#176) : ordre, rétention, fuseau | #176 | P2 | petite | Les trois tests sont verts ; sans le verrou, le test d'ordre échoue (noté dans la PR) |
| PR-H | `feat/sidebar-role-badge` (prod) | Badge nom et rôle | à créer | P2 | petite | Badge visible (vérification notée dans la PR) |

**Ce qui glisse, dans l'ordre** : PR-H, PR-G, PR-D (#177, sans effet sur S11 en staging), puis la reprise des orphelines quand l'outil n'est pas idempotent (elle passe en S9, #59). S11 n'est **fini** qu'avec PR-E **et** PR-F.

## Tests (1 à 3 par PR, ordre de CLAUDE.md)

- **Sécurité** : une ressource trouvée hors du registre du projet donne `foreign_resource`, rien n'est inscrit (PR-B).
- **Contrat** : dérive OpenAPI ; aller-retour de `ResourceRef.reused` (PR-A).
- **Nominal** : S11 en mémoire et S11 après redémarrage sur PostgreSQL (PR-E).
- **Régression** : une réservation orpheline après un échec ne bloque plus un plan identique (PR-C), le test qui aurait attrapé le trou 2. La garde de #183 est déjà couverte.

## Impact sur les contrats figés

Un seul champ facultatif est ajouté (`ResourceRef.reused`), sans passage en v2. Changements de comportement à signaler dans les PR :

- une ressource retrouvée n'est plus une erreur : avant, l'exécution finissait `blocked`, elle réussit maintenant ;
- la carte d'exécution liste aussi les ressources réutilisées ;
- `external_id` de `server_project` vaut maintenant `environnement/slug`.

## Risques

- Un adaptateur réel qui renseigne mal `created` réinscrirait une ressource : la contrainte d'unicité reste le filet (`DuplicateResource`, puis `blocked`).
- Avec D3, un outil mal déclaré idempotent serait rappelé. Le catalogue est relu par un humain ; les tests vérifient que les outils sans stratégie restent `blocked`.
- Clés GitLab au niveau du projet : après un `delete_created` (S3/S8), le rejeu renverrait un résultat périmé. À traiter avec #49 (invalider la clé à la compensation) ; ticket à créer.
- 0004 réécrit des données en ligne : `pg_dump` avant, `downgrade` testé.
- Le faux sans état durable n'est pas un modèle fidèle du redémarrage : c'est documenté dans le test.

## Côté serveur (propriétaire, restes S1 et S4)

1. **Avant de passer en `proxy_header`** : vérifier que Traefik **écrase** un `X-Forwarded-User` envoyé par le client (`curl -u dev:… -H 'X-Forwarded-User: admin' …/api/me` doit renvoyer `developer`). Ticket P1.
2. **#105** : vérifier le flux SSE derrière Traefik (buffering désactivé, maintien toutes les 15 s visible), capture à l'appui, puis fermer.
3. Déployer 0004 après un `pg_dump`, puis lancer S1 deux fois en ligne : le registre reste à 6 lignes.

## Tickets (jalon « PoC S5 — Semaine 5 : scénario S11 », sauf mention)

- **À créer** : plan S5 (P0) ; contrat S11 `ResourceRef.reused` (P0) ; reprise d'une réservation orpheline pour un outil idempotent (P1) ; badge de rôle dans la barre latérale (P2) ; contrôle Traefik avant `proxy_header` (P1, `track:infra`) ; `Idempotency-Key` HTTP sur `/projects` et `/messages` (P3, v1.1) ; invalider la clé GitLab après `delete_created` (P2, jalon Fournisseurs réels, lié à #49).
- **À corriger** : #41 (`## Critère de fin` = « test de gateway : ressource retrouvée réutilisée sans nouvelle ligne au registre ; S11 vert », priorité P0) ; #42 (remplacer « **Fin :** » par `## Critère de fin` : `test_s11_rejeu.py` et `test_s11_restart.py` verts en CI, carte « déjà présente » rendue depuis `s11-events.json`) ; #177 (garder P2, lier la migration 0004) ; #176 (déplacer au jalon S5).
