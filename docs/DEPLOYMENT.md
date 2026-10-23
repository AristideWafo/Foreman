# Déploiement

## Chaîne

`merge sur prod` → **Build** (image construite une seule fois, tag `sha-<commit>`, scan Trivy bloquant,
signature Cosign, SBOM, provenance) → **Deploy** automatique vers l'environnement GitHub **`env-perso`**
(qui joue le rôle du staging). Un déclenchement manuel de **Deploy** (avec un SHA) redéploie ou revient en arrière.
Un environnement `production` sera ajouté, avec relecteurs obligatoires, quand il existera.

On déploie le **digest** de l'image (`ghcr.io/...@sha256:...`), jamais un tag mobile. Pas de tag `latest`.

## Serveur contrôleur (une fois)

1. Installer Docker et copier `deploy/compose.yaml`, `deploy/Caddyfile` et un `.env` (voir `.env.example`) dans `/opt/foreman`.
2. Placer `deploy/deploy.sh` dans `/usr/local/bin/deploy` (exécutable).
3. Créer l'utilisateur `deploy` (groupe docker) et restreindre sa clé dans `authorized_keys` :

   ```
   command="/usr/local/bin/deploy",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA...
   ```

   La clé ne peut exécuter que `deploy <image@sha256:...>`, et le script refuse tout ce qui n'est pas un digest GHCR.
4. Pas de runner GitHub auto-hébergé sur cette machine : elle détient les secrets.

## GitHub (une fois)

- Environnement **`env-perso`** (Settings > Environments). Pas de relecteur obligatoire : le déploiement est
  automatique au merge.
- Variables de l'environnement : `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PORT` (défaut 22) et `DEPLOY_PROJECT` (nom du répertoire
  `/opt/<projet>` ; `foreman` par défaut). Secrets : `DEPLOY_SSH_KEY` (clé privée dédiée),
  `DEPLOY_KNOWN_HOSTS` (sortie de `ssh-keyscan`, vérifiée à la main).
- Protection de `prod` : check requis `CI OK`. `CODEOWNERS` est désactivé pour l'instant (un seul contributeur) : ne pas exiger de revue de propriétaire.

## Serveur avec Traefik existant (`deploy-custom.sh`)

Pour un serveur qui héberge déjà Traefik (conteneur), Grafana, cAdvisor, etc., et où chaque application vit
dans `/opt/<projet>`. Remplace `deploy.sh` et `compose.yaml` (qui supposent Caddy) pour ce cas.

**Ce que le script fait** : valide les entrées, crée `/opt/<projet>`, copie `compose.custom.yaml` en
`compose.yaml`, vérifie que le réseau Traefik existe, valide le compose, récupère l'image par son digest,
démarre avec `--wait` (attend le health check du conteneur), puis revient à la version précédente en cas d'échec.
Un verrou empêche deux déploiements simultanés d'un même projet.

**Ce que le compose déploie** :

- `app` : l'image du digest, détectée par Traefik grâce aux labels (routeur HTTPS avec certificat, redirection
  HTTP vers HTTPS, en-têtes de sécurité, compression, service sur le port 8000). Aucun port publié sur l'hôte.
  Système de fichiers en lecture seule, toutes les capacités retirées.
- `db` (option `--with-db`) : PostgreSQL sur un réseau privé, jamais visible de Traefik, avec volume persistant et health check.
- **Limites sur chaque conteneur** : CPU, mémoire, nombre de processus (réservation mémoire incluse), et rotation des
  journaux (10 Mo × 3). Valeurs modifiables dans `.env` (voir `.env.deploy.example`) ; cAdvisor et Grafana les voient
  sans configuration supplémentaire.

**Authentification : mode session (#228).** L'application authentifie elle-même (mot de passe, cookie
`HttpOnly; Secure; SameSite=Lax`, CSRF par en-tête `X-Foreman-CSRF`). Traefik ne pose plus de basicAuth ; il garde
HTTPS, la redirection, les en-têtes de sécurité et la compression. `/healthz` reste public. Dans `/opt/<projet>/.env` :

```
FOREMAN_AUTH_MODE=session
FOREMAN_PUBLIC_URL=https://<domaine>          # base des liens d'invitation (…/accept-invite#token=…)
FORWARDED_ALLOW_IPS=<sous-réseau du réseau Traefik>   # ex. 172.18.0.0/16
```

et **aucune** ligne `FOREMAN_BASIC_AUTH_USERS`. `FOREMAN_COOKIE_SECURE` reste à sa valeur par défaut (actif).
`FOREMAN_DATABASE_URL` est obligatoire (`--with-db`). `deploy-custom.sh` refuse le déploiement si, en mode session,
`FOREMAN_PUBLIC_URL` n'est pas en `https://`, si `FORWARDED_ALLOW_IPS` est absent, `*` ou `127.0.0.1`, si
`FOREMAN_COOKIE_SECURE=0`, ou si `FOREMAN_BASIC_AUTH_USERS` est encore défini (double authentification). Hors mode
session (`proxy_header`, `none`), le basicAuth reste **obligatoire** : le site ne peut pas être publié ouvert par oubli.

- **IP réelle et rate-limit.** Uvicorn n'accorde sa confiance qu'à `127.0.0.1` pour `X-Forwarded-For`
  (`FORWARDED_ALLOW_IPS`, lu nativement par uvicorn, aucun changement d'image). Sans le sous-réseau de Traefik, tous
  les clients partageraient l'IP de Traefik et donc une seule clé de limitation. Trouver le sous-réseau :
  `docker network inspect <TRAEFIK_NETWORK> --format '{{(index .IPAM.Config 0).Subnet}}'`. Ne jamais mettre `*`.
- **CSRF et Origin.** Traefik transmet le `Host` d'origine ; l'`Origin` du navigateur est comparé à ce `Host`
  (le schéma peut être terminé en amont). Aucun réglage supplémentaire tant que Traefik reste le seul point d'entrée.
- **SSE.** Le flux (GET) n'est plus authentifié par Traefik mais par le cookie de session. Aucun middleware de
  buffering n'est ajouté. **#105 (flux SSE derrière Traefik) reste à vérifier** sur le serveur.
- **`FOREMAN_DEV_MEMBERS`** n'est plus qu'un **amorçage** (migration `0003`, mode `proxy_header`) : en mode session, les
  équipes, membres, rôles et invitations se gèrent depuis `/admin` et la CLI. Plus aucune variable d'environnement à
  modifier pour gérer les membres.

### Procédure pas à pas (propriétaire)

1. **Sauvegarde AVANT la migration `0006`** (comptes, sessions, invitations) :

   ```bash
   cd /opt/<projet>
   docker compose -p <projet> exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > ~/avant-0006-$(date +%F).dump
   ```

   Copier ce dump hors du serveur. Le dump automatique de `deploy-custom.sh` existe aussi, mais celui-ci est nommé et conservé.
2. **Recopier** `deploy-custom.sh` et `compose.custom.yaml` sur le serveur (non synchronisés, voir « Limite connue »).
3. **Éditer `/opt/<projet>/.env`** : ajouter les trois variables ci-dessus et **supprimer** `FOREMAN_BASIC_AUTH_USERS`
   (garder l'ancienne ligne dans un coffre pour le retour arrière, jamais dans le dépôt).
4. **Déployer** (merge sur `prod`, ou **Deploy** manuel avec un SHA). La migration `0006` s'applique au démarrage.
5. **Créer le premier administrateur** (sur le serveur ; le lien s'affiche sur la sortie standard, jamais dans les journaux) :

   ```bash
   cd /opt/<projet>
   docker compose -p <projet> exec app foreman admin create --email wafoaristide@gmail.com
   ```

6. **Ouvrir le lien** (valable 1 h) dans le navigateur, **définir le mot de passe**, se connecter.
7. Depuis **/admin** : créer les équipes, inviter les membres (lien d'invitation à transmettre hors bande), régler les rôles.

### Retour arrière (tant que le mode `proxy_header` existe, jusqu'à #225)

Le retour d'image seul ne suffit pas : l'ancienne image ne démarre plus après `0006` (révision inconnue). Dans l'ordre :
arrêter `app`, restaurer le dump d'avant `0006` (procédure « Retour arrière après une migration » plus bas), puis dans `.env`
remplacer les trois variables par `FOREMAN_AUTH_MODE=proxy_header`, `FOREMAN_DEV_MEMBERS=…` et la ligne
`FOREMAN_BASIC_AUTH_USERS='utilisateur:empreinte'` (génération : `read -rs -p "Mot de passe : " PW; echo` puis
`printf "FOREMAN_BASIC_AUTH_USERS='admin:%s'\n" "$(openssl passwd -apr1 "$PW")" >> /opt/<projet>/.env; unset PW`),
et redéployer l'ancienne image. Le middleware basicAuth se rattache seul au routeur dès que `FOREMAN_BASIC_AUTH_USERS`
est défini (et `headerfield` écrase `X-Forwarded-User`, voir plus bas). Les comptes créés depuis `/admin` sont perdus avec le dump.

### Vérifications après déploiement (à noter dans le ticket #228)

1. `https://<domaine>/` charge en HTTPS ; `http://` redirige vers HTTPS ; connexion réussie avec le compte administrateur.
2. Cookie `foreman_session` présent avec `Secure`, `HttpOnly` et `SameSite=Lax` (outils du navigateur, onglet Stockage).
3. Sans cookie, `curl -s -o /dev/null -w '%{http_code}' https://<domaine>/api/projects` répond `401` ; un `POST` avec le cookie
   mais sans `X-Foreman-CSRF` (ou avec un `Origin` étranger) répond `403`.
4. Flux SSE : un message du chat affiche les événements au fil de l'eau (pas par paquets) ; clôt #105 si c'est le cas.
5. Rate-limit par IP réelle : après dépassement du seuil de tentatives de connexion depuis une IP, une **autre** IP n'est pas
   bloquée (sinon `FORWARDED_ALLOW_IPS` est mal réglé : `request.client` vaut l'IP de Traefik).
6. `https://<domaine>/healthz` répond sans authentification (`persistence: postgres`).

### Mode proxy_header (retour arrière, obsolète)

1. Sur le serveur, générer l'empreinte (le mot de passe ne s'affiche pas et n'entre pas dans l'historique) :

   ```bash
   read -rs -p "Mot de passe : " PW; echo
   printf "FOREMAN_BASIC_AUTH_USERS='admin:%s'\n" "$(openssl passwd -apr1 "$PW")" >> /opt/foreman/.env
   unset PW
   ```

   La valeur est entre apostrophes pour que les `$` de l'empreinte restent littéraux. Plusieurs utilisateurs :
   séparer par des virgules (`admin:...,bob:...`).

   **Identité et rôles (S4).** Traefik pose le nom authentifié dans `X-Forwarded-User` (label
   `basicauth.headerfield`, qui écrase tout en-tête du client).

   **Étape BLOQUANTE, avant de passer `.env` en `proxy_header`.** Recopier `compose.custom.yaml` (label
   `headerfield`) et redéployer. Puis vérifier que Traefik écrase l'en-tête envoyé par le client. En mode `none`
   l'application ignore l'en-tête et `/api/me` répond `dev` : le contrôle se fait donc avec un conteneur
   d'écho (`traefik/whoami`) placé derrière le même routeur et le même middleware basicAuth, ou sur une
   instance de test déjà en `proxy_header` :

   ```bash
   curl -s -u alice:… -H 'X-Forwarded-User: bob' https://<domaine>/<chemin-de-l-écho>
   ```

   L'écho doit afficher `X-Forwarded-User: alice`, jamais `bob`. Sinon, **ne pas activer `proxy_header`**.
   Sans le label `headerfield`, n'importe quel utilisateur basicAuth peut se faire passer pour un admin en
   envoyant l'en-tête lui-même.

   Seulement ensuite, ajouter dans le même `.env` (les noms sont ceux de `FOREMAN_BASIC_AUTH_USERS`) :

   ```
   FOREMAN_AUTH_MODE=proxy_header
   FOREMAN_DEV_MEMBERS=alice:developer,bob:team_admin
   ```

   - `FOREMAN_AUTH_MODE=none` (défaut, poste et CI) : utilisateur `dev` de rôle `developer`, l'en-tête est **ignoré**.
   - `proxy_header` : `FOREMAN_DEV_MEMBERS` est obligatoire (vide ou absent : l'application refuse de démarrer),
     sans nom en double. En-tête absent ou nom absent de la liste : `401 unauthenticated`, sans écho du nom.
   - Rôles possibles : `developer`, `team_admin`, `org_admin`. La liste est resynchronisée à chaque démarrage et
     **remplace** la précédente : retirer un nom retire son rôle (il perd l'accès à l'API, ses plans restent).
   - Ne jamais publier l'application sans Traefik en `proxy_header` : l'en-tête serait forgeable.
   - Contrôle après activation : `curl -u alice:… -H 'X-Forwarded-User: bob' https://<domaine>/api/me` doit
     répondre `alice` (rôle `developer`), pas `bob`.
   - Migration `0003` : faire un `pg_dump` avant le déploiement (voir PERSISTENCE.md).
2. Recopier `deploy-custom.sh` et `compose.custom.yaml` à côté l'un de l'autre sur le serveur (le compose n'est
   pas synchronisé automatiquement, voir « Limite connue »).
3. Redéployer (merge sur `prod`, ou **Deploy** manuel avec un SHA).
4. Vérifier : `curl -s -o /dev/null -w '%{http_code}' https://<domaine>/api/projects` renvoie `401` sans
   identifiants ; avec `-u admin:<mot de passe>` il répond ; `https://<domaine>/healthz` reste accessible sans
   identifiants.
   La version déployée est lue sur `curl https://<domaine>/healthz` (champ `version`) : elle vient du manifeste
   release-please au moment du build (`dev` hors release).

Le navigateur renvoie lui-même les identifiants au flux d'événements (même domaine). L'en-tête
`Authorization` est retiré par Traefik avant d'atteindre l'application. L'empreinte (pas le mot de passe) se
retrouve dans l'environnement du conteneur, puisque le `.env` entier est transmis ; elle ne doit pas être
commitée. Ce mode est conservé uniquement pour le retour arrière ; il disparaît avec #225.

**Installation (une fois par projet)** :

1. Copier `deploy/deploy-custom.sh` et `deploy/compose.custom.yaml` côte à côte sur le serveur
   (par exemple `/opt/deploy/`), script exécutable.
2. Créer `/opt/<projet>/.env` à partir de `.env.deploy.example` (au minimum `FOREMAN_DOMAIN`, `FOREMAN_AUTH_MODE=session`,
   `FOREMAN_PUBLIC_URL` et `FORWARDED_ALLOW_IPS` ; avec `--with-db`, aussi `POSTGRES_PASSWORD` et `FOREMAN_DATABASE_URL`,
   voir « Base de données » ci-dessous).
3. Si le registre est privé : `docker login ghcr.io` une fois avec un jeton en lecture seule.
4. Essai à blanc : `deploy-custom.sh --dry-run <projet> ghcr.io/<owner>/<repo>@sha256:<digest>`.

**Utilisation** :

```bash
deploy-custom.sh [--with-db] [<projet>] <image@sha256:digest>   # un seul argument : projet = $FOREMAN_PROJECT (foreman)
```

**Depuis le workflow `deploy.yml`** : la clé SSH est restreinte à ce script
(`command="/opt/deploy/deploy-custom.sh",no-port-forwarding,...`). Il accepte la forme `deploy <image>` déjà
envoyée par le workflow ; définir `FOREMAN_PROJECT` dans l'environnement de l'utilisateur de déploiement pour
choisir le répertoire `/opt/<projet>`.

### Base de données (`--with-db`)

Le workflow `deploy.yml` lance `deploy --with-db <projet> <image@sha256:…>` : le service `db` démarre avec l'application.
À renseigner **une fois**, dans `/opt/<projet>/.env` (jamais dans le dépôt) :

```bash
POSTGRES_PASSWORD='<mot de passe généré, p. ex. openssl rand -hex 24>'
# Hôte « db » : le service PostgreSQL du compose, sur le réseau privé.
FOREMAN_DATABASE_URL='postgresql+psycopg://foreman:<même mot de passe>@db:5432/foreman'
```

Si le mot de passe contient des caractères spéciaux, les encoder dans l'URL (`openssl rand -hex` n'en produit pas).

- Au démarrage, l'application applique les migrations Alembic sous un verrou consultatif PostgreSQL (deux instances qui
  démarrent ensemble s'exécutent l'une après l'autre), puis insère l'utilisateur et l'équipe de développement
  (idempotent). Si la base n'est pas encore prête, elle réessaie 5 fois à 2 secondes d'intervalle avant d'échouer
  (Compose relance alors le conteneur).
- Les projets, plans, approbations, exécutions, registre, audit **et le chat (journal d'événements)** sont en PostgreSQL
  et survivent à un redéploiement. Détails, rétention et limites : [PERSISTENCE.md](PERSISTENCE.md). Deux points
  d'exploitation :
  - **un seul processus** : le direct (SSE) est diffusé en mémoire du processus ; ne lancez pas plusieurs réplicas de
    `app` (ni `web` et `worker` séparés) sur la même base, le direct de l'un ne verrait pas les événements de l'autre ;
  - **messages en clair** : le texte des échanges est stocké tel quel dans `project_events` (donc dans les dumps).
- L'URL de la base n'est écrite dans aucun journal. La retirer du `.env` ramène l'application en mémoire.
- Le service `app` ne démarre qu'une fois `db` sain (`depends_on: service_healthy`, ignoré sans `--with-db`).
- **Contrôles de `deploy-custom.sh --with-db`** (valeurs jamais affichées) : Docker Compose 2.29 ou plus (limites `pids`) ;
  `POSTGRES_PASSWORD` présent ; `FOREMAN_DATABASE_URL` présent **une seule fois** sous la forme `NOM=valeur` (ni `export`,
  ni indentation, ni doublon), sans `$` ni `${VAR}`, de la forme `postgresql[+psycopg]://utilisateur:mot_de_passe@db:5432/base` ;
  et, quand l'URL n'a pas de `%`, mêmes utilisateur, mot de passe et base que `POSTGRES_USER` (défaut `foreman`),
  `POSTGRES_PASSWORD` et `POSTGRES_DB` (défaut `foreman`).
- `POSTGRES_PASSWORD` n'est appliqué qu'à **l'initialisation du volume** `db_data`. Changer le mot de passe plus tard
  se fait dans la base (`ALTER ROLE foreman PASSWORD '…'`) puis dans `.env` (les deux variables ensemble).
- **Sauvegarde automatique** : si le conteneur `db` tourne, le script lance `pg_dump -Fc` avant `up` vers
  `$DEPLOY_ROOT/backups/<projet>-<date>.dump` (répertoire 0700, fichiers 0600, 5 dumps conservés). Si le dump échoue,
  le déploiement est abandonné (code 70) et aucun fichier partiel n'est conservé. Au premier déploiement, rien n'est
  sauvegardé. Copier ces dumps hors du serveur reste à votre charge. Sauvegarde manuelle :

  ```bash
  cd /opt/<projet>
  docker compose -p <projet> exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > <fichier>.dump
  ```

- **Migration `0002_event_log`** (journal du chat) : elle ajoute `project_events` et `projects.last_event_seq`, sans
  réécriture de table ni verrou long. Le `pg_dump` automatique ci-dessus est donc pris **avant** elle ; **pas de retour
  arrière d'image sans restaurer ce dump** (l'ancienne image ne reconnaît plus la révision `0002`).
- **Migration `0004`** (identité `server_project` = `<environnement>/<projet>`) : réécrit `managed_resources.external_id`.
  Migrer puis redémarrer **sans exécution en vol** (une exécution entre `0004` et le nouveau code enregistrerait
  l'ancienne identité). Contrôle après migration, qui doit rendre `0` :
  `SELECT count(*) FROM managed_resources WHERE resource_type='server_project' AND external_id NOT LIKE '%/%';`
  `healthcheck.yaml` n'est pas modifié (classe `read`, sans registre).
- **Retour arrière après une migration** : le retour arrière automatique du script ne restaure que l'image, jamais la base.
  Si le déploiement ajoute une migration Alembic, l'ancienne image **ne redémarre plus** (révision inconnue d'Alembic).
  Il faut restaurer le dump pris avant ce déploiement **avant** de relancer l'ancienne image. `pg_restore --clean` ne
  supprime pas les tables créées par la migration plus récente : recréer la base d'abord.

  ```bash
  cd /opt/<projet>
  docker compose -p <projet> stop app
  docker compose -p <projet> exec -T db sh -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
  docker compose -p <projet> exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < <fichier>.dump
  deploy-custom.sh --with-db <projet> <ancienne image@sha256:…>
  ```

  (`dropdb` échoue tant que des connexions restent ouvertes : arrêter `app` d'abord, comme ci-dessus.)
- Par SSH, `SSH_ORIGINAL_COMMAND` prime sur les arguments : les options (`--with-db`, `--dry-run`) doivent figurer dans la
  commande `deploy …` envoyée ; celles passées en argument au script sont ignorées.
- `0005` (`plans.invalidation`, CHECK avec le statut) : `pg_dump` avant ; déployer migration et code ensemble (l'ancien
  `reject_admin` violerait le CHECK). Retour arrière : `alembic downgrade 0004` AVANT de remettre l'ancien code.
- **Migration `0006`** (comptes, mots de passe, sessions, invitations) : `pg_dump` avant (étape 1 de la procédure du mode session) ; pas de retour arrière d'image sans restaurer ce dump.
- Retour arrière d'une migration : jamais automatique. `downgrade()` supprime les tables (audit compris) ou le journal
  du chat (`0002`) ; il est refusé quand elles contiennent des données, sauf `FOREMAN_ALLOW_DESTRUCTIVE_DOWNGRADE=1`.
  Ne le lancer que sur une base de test.

**Hypothèses à confirmer** (valeurs par défaut, toutes surchargeables dans `.env`) : réseau Traefik `traefik`,
entrypoints `web` et `websecure`, résolveur de certificats `letsencrypt`, provider Docker de Traefik actif avec
`exposedByDefault=false`. Le premier déploiement réel sur votre serveur n'a pas été exécuté depuis
l'environnement de développement (pas de démon Docker) : seul le rendu du compose et la validation des entrées sont testés.

### Secrets chiffrés et clé maître (migration `0007`, #256)

Les clés et jetons saisis dans l'interface sont chiffrés (AES-256-GCM) en base (table `secrets`). La **clé maître**
est **générée automatiquement au premier démarrage** dans `/var/lib/foreman/secrets/master.key` (fichier `0600`),
sur le **volume Docker dédié `foreman_secrets`**. Aucune variable d'environnement à éditer
(`FOREMAN_SECRETS_KEY_FILE` existe pour le développement local seulement).

- **Avant le déploiement : recopier `compose.custom.yaml` (et `compose.yaml` pour la variante Caddy) sur le serveur.**
  Sans le volume, l'application ne peut pas écrire la clé (système de fichiers en lecture seule) et **refuse de démarrer**.
- **Sauvegarde séparée du `pg_dump`.** Le dump contient les secrets chiffrés, le volume contient la clé : les stocker
  ensemble annule le chiffrement. Sauvegarder le volume ailleurs et le restreindre :
  `docker run --rm -v <projet>_foreman_secrets:/s:ro alpine cat /s/master.key > master.key.bak` (puis chiffrer ou
  ranger dans un coffre ; ne jamais le committer).
- **Démarrage refusé** si la base contient des secrets mais que le fichier de clé est absent (volume perdu ou non monté) :
  l'application ne génère jamais une seconde clé, qui rendrait les secrets définitivement illisibles.
- **Perte de la clé = ressaisir les jetons** : restaurer le volume si possible ; sinon `DELETE FROM secrets` puis
  redémarrer (nouvelle clé) et ressaisir chaque clé/jeton depuis la page d'administration.
- **Rotation** : `docker compose -p <projet> exec app foreman secrets rotate` ajoute une nouvelle clé active et
  rechiffre tous les secrets (les anciennes clés restent dans le fichier, utile tant qu'une copie du dump est ancienne).
  `--prune` retire ensuite les anciennes clés : à utiliser sans saisie de secret en cours, et après avoir mis à jour la
  sauvegarde du volume (un ancien dump ne se relira plus qu'avec l'ancienne clé).

### Brancher `deploy-custom.sh` sur `env-perso`

1. Générer une clé dédiée : `ssh-keygen -t ed25519 -N "" -C "foreman-env-perso" -f ./foreman-env-perso`.
   La clé privée va dans le secret `DEPLOY_SSH_KEY`, puis le fichier local est supprimé.
2. Sur le serveur, dans `~<DEPLOY_USER>/.ssh/authorized_keys` (une ligne) :

   ```
   command="/opt/deploy/deploy-custom.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA... foreman-env-perso
   ```

   L'utilisateur doit pouvoir lancer `docker` (groupe `docker`, donc équivalent à root sur la machine : c'est
   pourquoi la clé ne peut exécuter que ce script, qui n'accepte qu'un digest GHCR).
3. Le workflow envoie `deploy <projet> <image@sha256:…>` ; le script valide tout avant d'agir.

**Limite connue** : `deploy-custom.sh` et `compose.custom.yaml` sont copiés sur le serveur à la main. Une modification de
`compose.custom.yaml` dans le dépôt (labels, limites) n'est donc **pas** appliquée par le déploiement : il faut recopier
le fichier. Une synchronisation automatique est possible plus tard ; elle donnerait à la CI le pouvoir de choisir
le contenu du compose, ce qui est un choix de sécurité à prendre explicitement.

## Déploiement du chat GitLab réel

PR #300 à #305 (ticket #299). Détail fonctionnel : `docs/integrations/gitlab.md`.

**Ordre de fusion** : cascade #300 (base `prod`), puis #301 et #305 **ensemble** (sans repli vers le faux, GitLab
réel complet d'un coup), puis #302, #303, #304, chacune après la fusion de sa base. **Tant que la PR #305
(écritures réelles) n'est pas fusionnée, les écritures réelles ne fonctionnent pas.** Déployer avec le jeton read
**et** le jeton write déjà présents : sans jeton, les outils GitLab échouent (`PermissionMissing`).

**Plans en attente** : la PR #302 change `budgets.per_turn` de `catalog/policy/matrix.yaml`, donc `policy_sha256` ;
les plans en attente d'approbation sont invalidés au déploiement. Prévenir les admins.

Vérifications :

1. `https://<domaine>/healthz` répond `persistence: postgres`.
2. Admin > Intégrations : les deux jetons GitLab (lecture `read_api`, écriture `api`) sont présents, puis cliquer
   **Tester**. Le jeton lecture doit avoir `read_api`, le jeton écriture `api`, aucun droit en trop.
   **Attention** : un état mémorisé avec les anciens scopes `simulated.*` est obsolète ; cliquer Tester pour le
   rafraîchir.
3. Le modèle Anthropic est choisi dans la même page.
4. Scénario d'essai : poser des questions de lecture (groupes, projets, un fichier) ; puis demander une création,
   vérifier la carte de plan (groupe parent), approuver avec un admin, constater le groupe créé (description
   `managed-by=foreman`).
5. Aucun jeton dans les logs : `docker logs <app> | grep -c glpat` doit afficher `0`.
6. Audit des appels GitLab :

   ```sql
   SELECT at, actor_kind, tool, tool_class, decision, rule_id, result_redacted
   FROM audit_events
   WHERE tool LIKE 'gitlab.%'
   ORDER BY at DESC LIMIT 50;
   ```

   Les lectures portent `rule_id = 'R1-lecture'` et `result_redacted` ne contient que la taille.

**Retour arrière** : `Deploy` en manuel avec le SHA précédent (section ci-dessous).

## Retour arrière

`Deploy` en manuel avec le SHA d'un commit précédent. Le script revient aussi seul à l'image
précédente si le health check échoue (`deploy-custom.sh`) ou si les trois contrôles de santé échouent (`deploy.sh`).

## Base du plan (foreman.plan/2, S12)

- Le contrôle de base a lieu à la validation du développeur et à l'approbation admin, pas à chaque appel de la gateway ; entre le contrôle et l'écriture, seule une autre exécution peut changer le registre (`execution_in_progress`, l'admin refait le contrôle).
- Un plan `foreman.plan/1` déjà en attente n'est plus approuvable (409 `plan_not_approvable`) et reste affiché `proposed` jusqu'à son échéance (24 h) ; son historique d'exécution est illisible (404).
