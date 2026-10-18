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

**Protéger l'accès (obligatoire).** Tout le site, flux SSE compris, est derrière une authentification HTTP
(`basicAuth` Traefik) ; seul `/healthz` reste public (supervision et vérification du déploiement). Sans
`FOREMAN_BASIC_AUTH_USERS` dans `/opt/<projet>/.env`, `deploy-custom.sh` et `docker compose` refusent de
déployer : le site ne peut pas être publié ouvert par oubli. Un mot de passe en clair est refusé aussi.

1. Sur le serveur, générer l'empreinte (le mot de passe ne s'affiche pas et n'entre pas dans l'historique) :

   ```bash
   read -rs -p "Mot de passe : " PW; echo
   printf "FOREMAN_BASIC_AUTH_USERS='admin:%s'\n" "$(openssl passwd -apr1 "$PW")" >> /opt/foreman/.env
   unset PW
   ```

   La valeur est entre apostrophes pour que les `$` de l'empreinte restent littéraux. Plusieurs utilisateurs :
   séparer par des virgules (`admin:...,bob:...`).
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
commitée. Ce mécanisme est provisoire : il sera remplacé par l'authentification de la semaine 4 (S10).

**Installation (une fois par projet)** :

1. Copier `deploy/deploy-custom.sh` et `deploy/compose.custom.yaml` côte à côte sur le serveur
   (par exemple `/opt/deploy/`), script exécutable.
2. Créer `/opt/<projet>/.env` à partir de `.env.deploy.example` (au minimum `FOREMAN_DOMAIN` et
   `FOREMAN_BASIC_AUTH_USERS` ; avec `--with-db`, aussi `POSTGRES_PASSWORD` et `FOREMAN_DATABASE_URL`,
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
- Les projets, plans, approbations, exécutions, registre et audit sont en PostgreSQL et survivent à un redéploiement ;
  le chat (événements) reste en mémoire et est vidé à chaque redémarrage.
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
- Retour arrière d'une migration : jamais automatique. `downgrade()` supprime les tables (audit compris) ; ne le lancer
  que sur une base de test.

**Hypothèses à confirmer** (valeurs par défaut, toutes surchargeables dans `.env`) : réseau Traefik `traefik`,
entrypoints `web` et `websecure`, résolveur de certificats `letsencrypt`, provider Docker de Traefik actif avec
`exposedByDefault=false`. Le premier déploiement réel sur votre serveur n'a pas été exécuté depuis
l'environnement de développement (pas de démon Docker) : seul le rendu du compose et la validation des entrées sont testés.

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

## Retour arrière

`Deploy` en manuel avec le SHA d'un commit précédent. Le script revient aussi seul à l'image
précédente si le health check échoue (`deploy-custom.sh`) ou si les trois contrôles de santé échouent (`deploy.sh`).
