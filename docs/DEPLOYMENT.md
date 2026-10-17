# Déploiement

## Chaîne

`push main` → **Build** (image construite une seule fois, tag `sha-<commit>`, scan Trivy bloquant,
signature Cosign, SBOM, provenance) → **Deploy staging** automatique → **Deploy production** manuel.

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

- Environnements `staging` et `production` ; `production` avec relecteurs obligatoires.
- Variables d'environnement : `DEPLOY_HOST`, `DEPLOY_USER`. Secrets : `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`
  (sortie de `ssh-keyscan`, vérifiée à la main).
- Protection de `main` : check requis `CI OK`, relecture CODEOWNERS.

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

## Retour arrière

`Deploy` en manuel avec le SHA d'un commit précédent. Le script revient aussi seul à l'image
précédente si les trois contrôles de santé échouent.
