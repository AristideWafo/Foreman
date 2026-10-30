# Intégration GitLab

Connecteur `gitlab` (gitlab.com). Ce que l'agent peut faire dans le chat, et comment le configurer.
Séries de PR : #300 à #305 (ticket #299).

## Ce que l'agent peut faire

- **Lire** (sans plan, ni carte, ni approbation) : 8 outils de classe `read`, appelés directement par le modèle
  pendant un tour de chat, via `Gateway.read`.
- **Écrire** : `gitlab.create_group` et `gitlab.create_project` ne sont jamais exposés au modèle comme outils.
  Il les propose comme étapes de `propose_plan` ; un admin approuve, puis le moteur exécute.

## Les 8 outils de lecture

| Outil | Rôle |
| --- | --- |
| `gitlab.list_groups` | Liste les groupes |
| `gitlab.list_projects` | Liste les projets d'un groupe (`group_id`, `search` facultatif) |
| `gitlab.get_project` | Détail d'un projet |
| `gitlab.list_branches` | Branches d'un projet |
| `gitlab.list_pipelines` | Pipelines d'un projet |
| `gitlab.list_issues` | Tickets d'un projet |
| `gitlab.list_merge_requests` | Merge requests d'un projet |
| `gitlab.read_file` | Contenu d'un fichier texte (`project_id`, `path`, `ref` facultatif) |

Bornes (imposées par l'adaptateur, pas par le modèle) :

- **10 éléments par page**, `page` de 1 à **10** au plus. Titres coupés à 80 caractères, 5 étiquettes de 20
  caractères au plus. Filet de **3500 octets par réponse** : les derniers éléments peuvent être écartés.
- **`read_file`** : contenu coupé à **480 caractères** (`truncated: true` au-delà), fichier de 64 Kio au plus ;
  contenu masqué ligne par ligne. La gateway coupe chaque chaîne à 500 caractères et borne la sortie à 4 Kio.
- **Fichiers refusés** : `.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, `id_ecdsa*`, `*.p12`,
  `*.pfx`, `.npmrc`, `.pypirc`, `.netrc`, `.git-credentials`, `*.tfstate`, `*.tfvars` ; binaires et fichiers de plus de 64 Kio.
- `Gateway.read` refuse les connecteurs non `available` (serveur, DNS).
- **Les lectures ne sont pas bornées au projet** : tout membre peut lire tout dépôt visible par le jeton `read` de
  la plateforme (décision assumée).
- Les champs renvoyés sont une liste d'autorisation (par exemple `runners_token` n'en fait pas partie).

## Jetons et configuration

Deux jetons d'accès personnels GitLab, saisis par un `org_admin` dans **Admin > Intégrations** :

| Jeton | Droit | Sert à |
| --- | --- | --- |
| lecture (`read`) | `read_api` | les 8 outils de lecture |
| écriture (`write`) | `api` | `create_group`, `create_project` |

Aucun autre droit ne doit être coché. Créez-les avec un compte Owner des groupes que Foreman doit gérer
(l'aide « Comment configurer ? » de la page détaille les étapes). Le bouton **Tester** interroge
`GET /personal_access_tokens/self` et indique si le droit attendu est présent, absent ou en trop. Les jetons ne sont
jamais renvoyés par l'API (seulement « présent / absent »).

## Faux ou vrai GitLab

| Situation | Backend |
| --- | --- |
| `CI` défini, profil EVAL ou `force_fake` | faux |
| Autre cas | vrai (jeton relu à chaque appel) |

Il n'y a **jamais de repli** : sans jeton, les outils GitLab échouent en `PermissionMissing` ; une erreur du vrai
GitLab est remontée, elle ne bascule pas sur le faux. Une écriture sans jeton `write` est refusée de même.
Impact : en développement local sans jeton, définir `CI=1` (faux) ou saisir un jeton.

## Flux d'écriture

1. Le modèle propose un plan (`propose_plan`) ; le parent est celui que **l'utilisateur désigne** (jamais choisi sur
   la foi d'un contenu lu), et le `full_path` du parent figure dans le titre de l'étape. La carte affiche le groupe parent.
2. Un admin approuve (matrice R1-R10 inchangée : un membre propose, l'admin approuve).
3. Le moteur exécute avec le jeton `write`.

Règles de l'adaptateur réel :

- **Parent** : `parent_group_id` est un entier > 0 ; il n'y a plus de groupe racine fixe. Le droit est vérifié
  **à chaque création** sur le compte du jeton `write` de la plateforme (pas sur l'utilisateur) : il doit être
  **Owner** (niveau GitLab 50) du groupe parent, sinon `PermissionMissing` et aucun POST. La vraie garde est
  l'approbation admin.
- **Isolation entre projets** conservée : un parent enregistré pour un autre projet donne `scope_violation`.
- **Marquage** : tout groupe ou projet créé porte `managed-by=foreman` dans sa description, visibilité privée.
- **Idempotence** : lecture puis création ; un existant marqué est réutilisé (`created=False`) ; un existant non
  marqué est refusé (`ForeignResource`).
- **Boilerplate** (go-api, vue-web) : le dépôt est créé vide avec un README, le boilerplate est seulement noté dans la
  description. L'import réel n'est pas fait (décision n°2 de la ROADMAP).

## Boucle d'outils et budgets

Un tour de chat peut enchaîner jusqu'à **5 tours d'outils** (`MAX_TOOL_ROUNDS`), avec **3 lectures** au plus par
réponse du modèle (au-delà : résultat d'erreur `limit_reached`). Un 6e tour d'outils donne `budget_exceeded`.
La durée du tour, lectures comprises, est bornée par `max_seconds`. Budgets par tour dans
`catalog/policy/matrix.yaml` : `max_model_calls` 6 (avant 4) et `max_tokens` 150000 (avant 60000) ; le coût reste de
0,5 EUR. La matrice R1-R10 est inchangée : seuls les budgets bougent. Le front affiche un événement `tool_call`
(`{tool, outcome}`, sans paramètres ni contenu) dans la trace du tour.

## Pause sur droit manquant

Si une lecture du chat est refusée avec le code `permission_missing` (sonde en échec, ou GitLab répond 401/403, ou jeton
absent), le tour s'arrête : le modèle n'est pas rappelé. Le front reçoit une carte `permission` (`connector`, `tool`,
`token`, `label`, `scopes`, `boundary`), puis `turn_status: completed`. Ces champs viennent de la déclaration du jeton
dans le catalogue, jamais d'un texte d'adaptateur ni d'une exception. La carte nomme le droit, renvoie vers
Administration > Intégrations (bouton « Vérifier ») et propose « Relancer » (même demande). Si la recherche dans le
catalogue échoue, le comportement reste celui d'avant (résultat d'erreur donné au modèle). Les exécutions ne sont pas
concernées (voir #54).

## Sécurité

- Le jeton n'est jamais exposé : ni dans les logs, ni dans les prompts, ni dans les erreurs (message fixe, un `glpat-`
  cité par GitLab est masqué). Pas de redirection suivie, base fixe `gitlab.com`.
- Les résultats de lecture sont des **données non fiables** : ils arrivent au modèle en blocs `tool_result`
  `{"tool", "untrusted_data"}`, masqués et aliasés, jamais en message `user`. Voir l'ADR 0002.
- Chaque lecture écrit une ligne d'audit (règle `R1-lecture`) avec la taille du résultat, jamais le contenu.
- `.gitleaksignore` (racine) liste les faux jetons de test par empreinte.
- Appels et résultats d'outils restent en mémoire pendant le tour, jamais dans le journal d'événements.
