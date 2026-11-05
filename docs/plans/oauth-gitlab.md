# Plan — Remplacer les jetons d'accès personnels GitLab par OAuth 2.0 (code d'autorisation + PKCE)

Plan écrit par l'agent `Plan` (Opus) à partir du code réel de `prod` 0.22.0. Il suit le format de `docs/plans/semaine-6.md` : 1 à 3 tests par fonctionnalité, `migrations/` relue attentivement, `gateway/` et `policy/` inchangés (D10).

Sources : documentation officielle GitLab consultée le 2026-11-05 (URL citées). Tout point non vérifié est marqué **NON CONFIRMÉ**.

## État de départ (vérifié dans le code)

| Élément | État |
| --- | --- |
| Connecteur | `integrations/gitlab/connector.yaml` déclare deux jetons, `read` (`read_api`) et `write` (`api`), l'aide « Comment configurer ? » (création d'un jeton personnel) et `tools_enabled_when` : les 8 lectures demandent `read`, `create_group` et `create_project` demandent `write`. Deux sondes : `lire_groupes` (`GET /groups?per_page=1`, jeton `read`) et `jeton_ecriture_valide` (`GET /personal_access_tokens/self`, `expects: usable >= 1`) |
| Client (`client.py`) | Base fixe `https://gitlab.com/api/v4`. En-tête **`PRIVATE-TOKEN`**. Le jeton est relu à chaque appel dans le `SecretStore` (`connector_secret_id("gitlab", name)`, type `CONNECTOR_TOKEN_KIND`). `post()` n'utilise que le jeton `write`. 401/403 donnent `PermissionMissing`. Erreurs à code fermé, aucune redirection suivie, délai 10 s, corps limité à 256 Kio |
| Adaptateur (`adapter.py`) | `_owner_check` lit `user_id` sur `/personal_access_tokens/self` (jeton `write`), puis `GET /groups/:id/members/all/:user_id` et exige `access_level >= 50`. `probe()` lit les scopes sur `/personal_access_tokens/self`. Ces deux appels n'existent que pour les jetons personnels |
| Branchement (`bootstrap/adapters.py`) | `ConfiguredGitLab` refuse une écriture si le secret `connector.gitlab.write` est absent. Le faux GitLab est utilisé si `CI` est défini, en profil EVAL ou avec `force_fake` |
| Secrets (0007) | AES-256-GCM. Données authentifiées : `secret_id` et `kind`. Port `SecretStore` : `put`, `get`, `delete` (booléen), `exists`, `rotate`. **Aucun verrou** |
| État des connecteurs (0008) | Table `connectors`, `CHECK status IN ('ok','incomplete','revoked')`, `read_secret_ref`, `write_secret_ref`. `save_change` et `save_probe` écrivent l'audit `integration.<action>` dans la même transaction, avec `actor_kind='user'` uniquement |
| API (`surfaces/web/admin_integrations.py`) | Réservée à l'org_admin, mode `session` seulement. Routes : `GET /integrations`, `PUT /{c}/credentials` (jeton en écriture seule), `DELETE /{c}/credentials`, `POST /{c}/test` (via `gateway.probe`), `PUT /anthropic/model`. `ProbeLimiter` : 10 par minute et par acteur |
| Session et CSRF (`surfaces/web/auth.py`) | Cookie `foreman_session` (`HttpOnly`, `SameSite=lax`). Toute méthode non sûre exige `X-Foreman-CSRF` et un `Origin` de même hôte |
| URL publique | `FOREMAN_PUBLIC_URL` existe déjà ; `deploy-custom.sh` impose `https://` |
| Exécution bloquée | `core/execution/cards.py::_CAUSES` n'a **pas** d'entrée `permission_missing` : une écriture refusée faute de droit affiche « Rien d'autre n'a été lancé. » |
| Front | `features/admin/IntegrationRow.tsx` (champ de jeton, menu « Jeton à enregistrer », Tester, Révoquer), `IntegrationHelp.tsx`, `useAdmin.ts`. `AdminPage` utilise `Tabs defaultValue="teams"`, sans paramètre d'URL |
| Tests | `tests/test_gitlab_real.py` (faux transport, jetons `glpat-`), `test_connector_probe.py`, `test_permission_pause.py`. `tests/db/test_integrations_api.py` ne tourne qu'en CI (PostgreSQL). 28 échecs préexistants dans `test_deploy_custom.py`, hors sujet |
| Tickets | Ouverts : #47 (sondes et jetons, P1), #48, #299. Aucun ticket OAuth. Jalon 17 « PoC — Intégrations et LLM » |

## Ce que dit la documentation officielle (consultée le 2026-11-05)

- **https://docs.gitlab.com/api/oauth2/**
  - Flux PKCE. Autorisation : `client_id`, `redirect_uri`, `response_type=code`, `state`, `scope`, `code_challenge`, `code_challenge_method=S256`. Échange : `client_id`, `code`, `grant_type=authorization_code`, `redirect_uri`, `code_verifier`.
  - Rafraîchissement : `grant_type=refresh_token`, `refresh_token`, `redirect_uri` ; « Invalidates the existing access_token and refresh_token » : c'est une **rotation**.
  - `GET /oauth/token/info` renvoie `resource_owner_id`, `scope` (tableau), `expires_in`, `application.uid`, `created_at`.
  - `POST /oauth/revoke` prend `client_id`, `client_secret`, `token` ; succès : 200 `{}`.
  - Le secret client va dans le corps **ou** dans un en-tête Basic, pas les deux (sinon 400).
  - `state` : « an unpredictable value », utilisable comme jeton CSRF. Le `redirect_uri` de l'échange doit être celui de l'autorisation. **Rien** sur les rafraîchissements concurrents.
- **https://docs.gitlab.com/integration/oauth_provider/** : sur gitlab.com, une application appartient à un utilisateur ou à un groupe (pas d'application d'instance). Jeton d'accès valable 2 h (7200 s). Scopes `api` et `read_api` proposés. Le secret peut être renouvelé, ce qui casse l'application.
- **https://docs.gitlab.com/security/tokens/access_token_scopes/** : `read_api` = lecture de l'API ; `api` = lecture et écriture complètes. Aucun scope plus étroit ne permet de créer groupes et projets.
- **NON CONFIRMÉ** :
  - la case « Confidential » et son effet sur `client_secret` avec PKCE ;
  - la durée de vie d'un jeton de rafraîchissement inutilisé ;
  - plusieurs Redirect URI par application ;
  - **qu'une deuxième autorisation de la même application, avec un autre scope, ne révoque pas la première** (clé de D2) ;
  - que révoquer le jeton de rafraîchissement révoque aussi le jeton d'accès.

## Décisions à trancher (recommandation en premier)

| # | Question | Recommandation |
| --- | --- | --- |
| D1 | Par organisation ou par utilisateur | **Par organisation.** Un org_admin autorise une fois par emplacement (`read`, `write`). Jetons chiffrés dans le `SecretStore` sous les **mêmes identifiants qu'aujourd'hui** (`connector.gitlab.read` / `.write`) : colonnes `read_secret_ref` / `write_secret_ref`, flux du plan, matrice et approbation ne changent pas. **Évolution par utilisateur (P3, v1.1)** : table `oauth_connections(user_id, connector)` ; lectures avec le compte du demandeur, écritures avec celui de l'approbateur. Pas maintenant : elle demande un modèle d'identité GitLab par membre |
| D2 | Scopes, séparation lecture/écriture | **Deux autorisations de la même application** : `read` demande `scope=read_api`, `write` demande `scope=api`. On garde la défense en profondeur : les lectures du chat ne détiennent jamais un jeton capable d'écrire. L'application est enregistrée avec les deux scopes. **Contrôle Owner** : `_owner_check` n'appelle plus `/personal_access_tokens/self` ; il prend le `resource_owner_id` enregistré dans le paquet `write` (lu sur `/oauth/token/info` à la connexion), puis `GET /groups/:parent/members/all/:id` à chaque création. C'est le compte gitlab.com connecté lors de l'autorisation `write` qui doit être Owner (de préférence un compte de service). **Repli si le point NON CONFIRMÉ est faux** : une seule autorisation `api` enregistrée dans les deux emplacements ; la séparation par le code reste (`post()` réservé à `write`). Le choix se fait au test manuel sur staging et est noté dans la PR |
| D3 | `client_id` / `client_secret` | Saisis par l'org_admin via **`PUT /api/admin/integrations/{c}/oauth/client`** `{client_id, client_secret: SecretStr}`. Rangés dans le `SecretStore` sous `connector.gitlab.oauth_client`, type `oauth_client`, JSON chiffré. **Jamais renvoyés** : l'API répond `client_configured: bool`. Corps jamais journalisé ; opération auditée sans les valeurs. Le secret est conservé (rafraîchissement et révocation l'exigent) ; envoyé dans le corps seulement |
| D4 | Flux | (1) **`POST /api/admin/integrations/{c}/oauth/start`** `{token: "read"\|"write"}` → `200 {authorize_url}` (POST : CSRF et `Origin` déjà vérifiés ; le front fait `location.assign`). (2) **`GET /api/admin/integrations/{c}/oauth/callback?code&state[&error]`** → `303` vers `/admin?tab=integrations&oauth=connected\|denied\|failed`, sans corps ni écho de `code`/`state`/`error`. (3) Déconnexion : D8. **`state`** : 32 octets aléatoires ; état en attente **dans le `SecretStore`** : id `oauth_state.<sha256(state)>`, type `oauth_state`, valeur `{session_hash, user_id, connector, token, code_verifier, exp}`. Au retour : `delete()` doit renvoyer `True` (usage unique, pas de rejeu), `exp` non dépassé (**10 min**), `token_hash(cookie) == session_hash`, même `user_id`, appelant toujours org_admin, connecteur identique. Tout écart → `oauth=failed`, rien de stocké, audit. **PKCE S256** : `code_verifier = token_urlsafe(64)`, `code_challenge = base64url(sha256(verifier))`. **Redirect URI** : `FOREMAN_PUBLIC_URL + "/api/admin/integrations/gitlab/oauth/callback"`, identique à l'autorisation, l'échange et le rafraîchissement ; affichée dans la page. Réponse du retour : `Cache-Control: no-store`, `Referrer-Policy: no-referrer`. Limite : celle de `set`. Après un échange réussi, `gateway.probe` au mieux |
| D5 | Rafraîchissement | Paquet par emplacement (type `connector_oauth`) : `{access_token, refresh_token, expires_at, scope, resource_owner_id}`. Dans `GitLabClient._token(name)` : si `expires_at - now < 120 s`, `async with secrets.lock(secret_id)`, **relecture** du paquet, rafraîchissement si encore nécessaire, `put` du nouveau paquet **avant** de libérer le verrou. Horloge injectable. **Verrou** : `SecretStore.lock(secret_id)` ; mémoire : un `asyncio.Lock` par id ; PostgreSQL : `pg_advisory_lock(hashtextextended(secret_id, 0))` sur une connexion dédiée, `unlock` dans `finally`, sous `asyncio.timeout(15)` (dépassement → `gitlab_error("unavailable")`). **Échec** : 400/401 `invalid_grant` → `ConnectorStore.mark_reauth` (statut `reauth_required`, audit `actor_kind=system`) puis `PermissionMissing`. Dans une exécution : `_CAUSES["permission_missing"]` = « Le connecteur a perdu ses droits (reconnexion requise ou droit manquant). Un administrateur doit le reconnecter dans Administration > Intégrations, puis relancez le plan. » 5xx ou réseau → `unavailable`, **sans** `reauth_required`. Logs : code seul (`oauth_refresh_failed`), jamais de corps ni de jeton |
| D6 | Passage depuis les PAT | **Remplacement net en une version** (AGENTS.md : pas de couche de compatibilité). Migration **0009** : supprime les secrets `connector.gitlab.read` / `.write` et passe la ligne `gitlab` de `connectors` à `reauth_required`. Retrait du chemin PAT dans la même pile : `PRIVATE-TOKEN`, `_PAT_SELF`, aide et étapes de création de jeton, `PUT /credentials` pour GitLab (404), menu « Jeton à enregistrer », faux jetons `glpat-` et `.gitleaksignore`. Validation avant coupure : image de PR-D déployée sur **staging**, scénario réel joué par le propriétaire **avant** la PR de version. Retour arrière : image précédente + `downgrade` 0009 ; les jetons personnels supprimés doivent être ressaisis |
| D7 | Sonde | `GET https://gitlab.com/oauth/token/info` (hors `/api/v4`), `Authorization: Bearer`. Fournit `scope` (verdicts ok / manquant / en trop) et `resource_owner_id`. Sonde `write` : `{name: jeton_ecriture_valide, token: write, call: "GET /oauth/token/info", expects: "usable >= 1"}` ; `usable` = 1 si 200 et `api` dans `scope`, 401 = droit manquant. Sonde `read` inchangée. La sonde rafraîchit si besoin via `_token` |
| D8 | Révocation | « Déconnecter » réutilise `DELETE /api/admin/integrations/{c}/credentials`. Pour un connecteur OAuth : `POST /oauth/revoke` sur le jeton de rafraîchissement **puis** sur le jeton d'accès, au mieux (échec journalisé par son code). Les secrets locaux sont **toujours** supprimés, puis `save_change("oauth.disconnect")` → statut `revoked`. Le couple client (D3) est conservé |
| D9 | Audit | `integration.<action>` dans la même transaction, sans valeur secrète. Actions ajoutées : `oauth.client.set`, `oauth.connect` (`{connecteur, jeton, compte_gitlab: resource_owner_id}`), `oauth.disconnect`, `oauth.reauth_required` (`actor_kind=system`), `oauth.refused` (raison : `state_unknown`, `state_expired`, `session_mismatch`, `denied`, `exchange_failed`) |
| D10 | Gateway et matrice | **Aucun changement.** `PermissionMissing` → `permission_missing` existe déjà (`pipeline.py`). Seule retouche voisine : `core/execution/cards.py::_CAUSES`. **Faux** : `FakeGitLabOAuthServer` (`tests/gitlab_oauth_fake.py`) simulant `/oauth/token` (code lié au challenge S256, à usage unique ; rafraîchissement **avec rotation**, ancien jeton → `400 invalid_grant` ; compteur d'appels), `/oauth/token/info`, `/oauth/revoke` et les routes `/api/v4` déjà simulées. Aucun réseau en CI |

## Volet agentique

- Skills, prompt, matrice R1-R10, budgets, classes et réversibilité des outils : **inchangés** (10 outils GitLab gardent leurs YAML).
- `Provider` : aucun nouvel enregistrement. S1, S10, S11, S12 utilisent le faux GitLab.
- Fakes : `FakeGitLabOAuthServer` (D10). `SimulatedGitLab` ne change pas.
- Effet visible : la carte `permission` peut venir d'un `reauth_required`. Ses champs ne changent pas.

## Volet back-end

- **Contrats (ajouts, `v` des événements inchangé)** : `IntegrationView.auth: "token" | "oauth"` ; `IntegrationView.oauth?: {client_configured, redirect_uri}` ; `IntegrationView.status` reçoit `reauth_required` ; `OAuthClientRequest`, `OAuthStartRequest`, `OAuthStartResponse` ; `TokenView.configured` = « connecté » pour OAuth. Lancer `make api-types`.
- **Modules** :
  - `core/secrets.py` : `SecretStore.lock` ; `infra/secrets.py` et `infra/db/secrets.py` ;
  - `core/connector_state.py` : `reauth_required`, actions de D9, `mark_reauth`, type `CONNECTOR_OAUTH_KIND` ; `infra/db/connectors.py` (et en mémoire) ;
  - `core/ports.py` : port `OAuthConnector` (`authorize_url`, `connect`, `disconnect`) ; l'implémentation détient le `SecretStore`, la surface ne voit jamais un jeton ;
  - `core/execution/cards.py` : `_CAUSES["permission_missing"]` ;
  - `integrations/gitlab/oauth.py` (nouveau), `client.py` (Bearer, rafraîchissement sous verrou, `token_info()`), `adapter.py` (`_owner_check` via `resource_owner_id`, `probe` via `token/info`, `_PAT_SELF` supprimé), `connector.yaml` ;
  - `bootstrap/adapters.py` (`build_oauth`), `bootstrap/configure.py` (`App.oauth`) ;
  - `surfaces/web/admin_integrations.py` et `schemas.py` : routes D3, D4, D8 ; `PUT /credentials` → 404 pour un connecteur OAuth.
  - `make check-imports` reste vert (`integrations` n'importe que `core`).
- **Migration `0009_gitlab_oauth`** (relecture propriétaire, `pg_dump` avant) : nouveau `CHECK status IN ('ok','incomplete','revoked','reauth_required')` ; `DELETE FROM secrets WHERE id IN ('connector.gitlab.read','connector.gitlab.write')` ; `UPDATE connectors SET status='reauth_required', verified_scopes='{}' WHERE provider='gitlab'`. `downgrade` : `reauth_required` → `revoked`, ancien `CHECK` rétabli ; les secrets supprimés ne reviennent pas (écrit dans la migration).
- **Sécurité** : aucun jeton, `code`, `code_verifier` ou `client_secret` dans un log, une réponse, l'audit ou une URL produite par nous ; le retour ne renvoie jamais le corps d'erreur de GitLab ; `state` à usage unique lié à session et admin ; PKCE S256 ; rôle org_admin revérifié au retour ; erreurs opaques ; aucun appel bloquant ; verrou PostgreSQL borné dans le temps. **Point connu** : le `code` apparaît dans l'URL de retour (journaux d'accès uvicorn/Traefik) ; accepté : usage unique, courte durée, inutilisable sans `code_verifier`. À écrire dans `docs/integrations/gitlab.md`.

## Volet front-end

- **`DESIGN.md`** : section « Intégrations », sous-partie « Connexion OAuth (GitLab) ».
- **`IntegrationRow`** (si `auth === "oauth"`) : bloc « Application OAuth » (`client_id` texte, `client_secret` en `type="password"` `autocomplete="new-password"`, vidé dès l'envoi, jamais en cache ni en URL) avec badge « Application enregistrée » ; URI de redirection en `code` avec « Copier » ; par emplacement « Connecter » / « Reconnecter » (désactivé tant que `client_configured` est faux) ; badge « Reconnexion requise » (`destructive`, avec texte) ; « Tester » inchangé ; « Déconnecter » via `ConfirmDialog`.
- **`AdminPage`** : lit `?tab=` et `?oauth=` (Alert « GitLab connecté » / « Autorisation refusée sur GitLab » / « La connexion a échoué, recommencez »), puis `history.replaceState`.
- **`IntegrationHelp`** : lien « Ouvrir la page des applications OAuth » ; étapes toujours issues du YAML.
- `client.ts`, `useAdmin.ts` : `setOAuthClient`, `startOAuth`. Types régénérés. Test de rendu léger : états « application absente », « connecté », « reconnexion requise ».

## Tests (1 à 3 par fonctionnalité, ordre de CLAUDE.md)

- **Sécurité** (PR-D, `tests/db/test_integrations_api.py`, CI) : (1) retour avec `state` inconnu, rejoué, expiré, d'une autre session ou d'un autre admin → `oauth=failed`, rien de stocké, audit `oauth.refused` ; un team_admin reçoit 403 sur `start`, `client`, `callback` ; (2) `GET /integrations` ne contient ni `client_secret`, ni jeton, ni `code` (réponse JSON et `caplog`).
- **Rafraîchissement et concurrence** (PR-C ; verrou PostgreSQL en CI en PR-B) : (3) 10 lectures concurrentes avec jeton expiré → **un seul** `POST /oauth/token`, nouveau jeton de rafraîchissement enregistré ; (4) `invalid_grant` → `PermissionMissing`, `reauth_required`, audit système, aucun jeton dans `caplog` ; (5) contrat `SecretStore.lock` sur les deux backends.
- **Contrat** : dérive OpenAPI (PR-A) ; 0009 montée / descente / `CHECK` / secrets supprimés (PR-B, vrai PostgreSQL).
- **Nominal** (PR-D) : `start` → échange du `code` sur le faux → `callback` → paquet stocké → sonde `ok` → audit `oauth.connect` ; « Déconnecter » appelle `/oauth/revoke`, supprime les secrets, statut `revoked`.
- **Régressions conservées et adaptées** dans `test_gitlab_real.py` : fuite de jeton dans une erreur 500, aucun repli vers le faux, contrôle Owner avant tout POST, idempotence des créations. Exécution bloquée (PR-C) : `permission_missing` affiche la nouvelle cause.

## Pile de PR (back-end en série ; front dès que PR-A est fusionnée)

| PR | Branche (base) | Contenu | Ticket | Prio | Critère de fin observable |
| --- | --- | --- | --- | --- | --- |
| PR0 | `docs/plan-oauth-gitlab` (prod) | Ce plan, ligne ROADMAP, tickets | à créer | P0 | Plan fusionné ; tickets créés avec priorité, jalon 17 et `## Critère de fin` |
| PR-A | `feat/contract-oauth` (prod) | Schémas D3/D4/D9, `reauth_required`, `auth`, `oauth`, `openapi.json`, types TS (routes déclarées, 501 provisoire) | à créer | P0 | Contrôle de dérive OpenAPI vert |
| PR-B | `feat/oauth-store` (PR-A) | `SecretStore.lock` (deux backends), `mark_reauth`, nouvelles actions, migration 0009 | à créer | P1 | Contrat du verrou vert (mémoire + PostgreSQL) ; 0009 montée et descente vertes en CI |
| PR-C | `feat/gitlab-oauth-client` (PR-B) | `oauth.py`, client Bearer et rafraîchissement, adaptateur, `connector.yaml`, `bootstrap`, `_CAUSES`, `FakeGitLabOAuthServer` ; retrait de `PRIVATE-TOKEN` et `_PAT_SELF` | à créer | P1 | Tests 3, 4 et exécution bloquée verts ; `test_gitlab_real.py` adapté et vert |
| PR-D | `feat/gitlab-oauth-routes` (PR-C) | Routes `client`, `start`, `callback`, déconnexion OAuth, `PUT /credentials` → 404 pour GitLab, sonde après connexion | à créer | P1 | Tests 1, 2 et nominal verts en CI ; **scénario réel joué sur staging par le propriétaire** |
| PR-E | `feat/front-gitlab-oauth` (PR-A) | Ligne OAuth, `AdminPage ?tab ?oauth`, `DESIGN.md`, test de rendu | à créer | P1 | Test de rendu vert ; capture des trois états dans la PR |
| PR-F | `docs/gitlab-oauth` (PR-D) | `docs/integrations/gitlab.md`, `DEPLOYMENT.md`, `.gitleaksignore` nettoyé, ROADMAP | à créer | P2 | Doc relue ; `grep -ri "personal_access_token\|glpat\|PRIVATE-TOKEN" backend/src frontend/src docs` ne renvoie rien |

**Règle de version** : PR-B à PR-E doivent toutes être dans `prod` **avant** la PR de version de release-please, sinon une version intermédiaire supprime les jetons personnels (0009) sans proposer de connexion. **Ce qui peut glisser** : la sonde automatique au retour, puis PR-F.

## Impact sur les contrats figés

- **Ajouts** : `auth`, `oauth`, `reauth_required`, trois routes.
- **Changements de comportement à signaler** : `PUT /integrations/gitlab/credentials` répond 404 ; les jetons personnels enregistrés sont supprimés par 0009 ; `TokenView.configured` signifie « connecté » pour GitLab.
- Aucun changement des événements SSE ni des cartes.

## Risques

- **NON CONFIRMÉ de D2** : repli à une seule autorisation `api`, connu au test sur staging.
- **Perte de rotation** : si le processus meurt entre la réponse de GitLab et le `put`, l'ancien jeton de rafraîchissement est invalide : `reauth_required` au prochain usage, reconnexion nécessaire (rare, visible).
- **`code` dans les journaux d'accès** : PKCE en limite la portée ; filtrage Traefik possible (P3).
- **États en attente abandonnés** (`oauth_state.*`) : inutilisables après 10 min, volume limité par `throttle`. Code : `shortcut: pas de purge, à ajouter si secrets > N lignes`.
- **Secret de l'application renouvelé sur gitlab.com** : le rafraîchissement échoue → `reauth_required` ; l'admin ressaisit le client.
- **Durée de vie d'un jeton de rafraîchissement inutilisé** : NON CONFIRMÉ ; même symptôme, lisible.
- **Plusieurs instances** : le verrou est correct entre conteneurs ; le cache de `ConnectorProbes` reste par processus (dette existante).
- **Fenêtre de déploiement** : entre le déploiement et la connexion de l'admin, les outils GitLab échouent en `permission_missing` ; déployer hors usage, puis se connecter tout de suite.

## Côté propriétaire

1. **Enregistrer l'application OAuth sur gitlab.com** (de préférence une application **de groupe** dans le groupe racine, Settings > Applications) : Name `Foreman` ; **Redirect URI** `https://<domaine>/api/admin/integrations/gitlab/oauth/callback` (valeur **exacte** affichée dans la page) ; scopes **`api`** et **`read_api`**, rien d'autre ; « Confidential » coché (NON CONFIRMÉ dans la doc).
2. Copier l'Application ID et le Secret dans `/admin` > Intégrations > GitLab.
3. Se connecter à gitlab.com avec le **compte Owner** des groupes parents (de préférence un compte de service), puis « Connecter » la lecture puis l'écriture.
4. `pg_dump` avant 0009. Jouer le scénario réel sur staging : connecter, Tester `ok`, plan de création approuvé, « Déconnecter ». Vérifier dans GitLab que l'autorisation a disparu (Avatar > Edit profile > Applications > Authorized applications).
5. Le secret de l'application ne vit que dans le `SecretStore`, jamais dans le dépôt ni le `.env`.

## Tickets (jalon 17 « PoC — Intégrations et LLM »)

- **P0** : plan OAuth GitLab (PR0) ; contrat OAuth (PR-A).
- **P1** : verrou de secret et migration 0009 (PR-B) ; client OAuth, rafraîchissement et sonde `token/info` (PR-C) ; routes start, callback, client et déconnexion (PR-D) ; écran de connexion OAuth (PR-E).
- **P2** : documentation et retrait des traces des jetons personnels (PR-F).
- **P3** : connexion GitLab par utilisateur (v1.1, D1) ; purge des états OAuth expirés ; filtrage du `code` dans les journaux d'accès de Traefik.
- **À mettre à jour** : #47 (jetons personnels remplacés par OAuth, lien vers ce plan) ; #299 (le déploiement sur staging inclut l'enregistrement de l'application OAuth).
