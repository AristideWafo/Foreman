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

## Retour arrière

`Deploy` en manuel avec le SHA d'un commit précédent. Le script revient aussi seul à l'image
précédente si les trois contrôles de santé échouent.
