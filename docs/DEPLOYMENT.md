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
- Protection de `prod` : check requis `CI OK`, relecture CODEOWNERS.

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

**Installation (une fois par projet)** :

1. Copier `deploy/deploy-custom.sh` et `deploy/compose.custom.yaml` côte à côte sur le serveur
   (par exemple `/opt/deploy/`), script exécutable.
2. Créer `/opt/<projet>/.env` à partir de `.env.deploy.example` (au minimum `FOREMAN_DOMAIN` ; avec `--with-db`,
   aussi `POSTGRES_PASSWORD`).
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
