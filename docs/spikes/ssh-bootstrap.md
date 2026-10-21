# Essai jetable : bootstrap et wrapper Compose (ticket #46)

Statut : **essai NON EXÉCUTÉ**. Aucune commande de ce document n'a été lancée sur un conteneur.

## Pourquoi rien n'a été exécuté

Environnement de l'essai (poste du propriétaire, 2026-10-21) :

```
$ docker info
(eval):1: command not found: docker
```

La CLI `docker` est absente du `PATH`. OrbStack est installé (`/Applications/OrbStack.app`) mais arrêté (`orbctl status` renvoie `Stopped`). Le démarrer n'a pas été fait sans accord : l'exécution est reportée. Aucun conteneur ni image n'a été créé, donc rien à nettoyer.

Le script et le wrapper n'existent que comme extraits de `dev platform .md` (sections « Script de bootstrap » et « Wrapper Docker Compose ») ; le gabarit `platform-compose.tpl` n'est pas un fichier du dépôt.

## Cas d'abus

| # | Cas | Commande / entrée prévue | Résultat |
| --- | --- | --- | --- |
| 1 | Compose privilégié | `sudo platform-compose-staging validate p` avec `privileged: true` | non exécuté |
| 2 | Montage hors projet | idem avec `volumes: ["/:/host"]` | non exécuté |
| 3 | `network_mode: host` | idem avec `network_mode: host` | non exécuté |
| 4 | Arguments hostiles | `... up '../x'`, `'p;id'`, argument vide, `-f /etc/x` | non exécuté |
| 5 | Symlink sur le répertoire projet | `ln -s / /srv/platform/staging/p` puis `validate p` | non exécuté |
| 6 | Retirer les restrictions de clé | `plat-staging` modifie `~/.ssh/authorized_keys` ou `/etc/ssh/authorized_keys.d/plat-staging` | non exécuté |

Aucun « refusé » ni « cassé » n'est affirmé : le critère de fin du ticket (six cas exécutés) n'est **pas atteint**.

## Ce qui marche / ce qui casse

Non établi par l'exécution. Rien à rapporter.

## Hypothèses issues de la relecture statique (à confirmer ou infirmer à l'essai)

Lecture du texte uniquement, aucune sortie réelle derrière. Chacune devient un test lors de l'exécution.

1. **Contournement du contrôle de montage** : le filtre jq ne regarde que `.volumes[]` de type `bind`. Un volume nommé avec `driver_opts` (`type: none, o: bind, device: /`), un `secrets:`/`configs:` avec `file:` hors projet, ou un `env_file:` hors projet ne sont pas contrôlés. Un `env_file` est lu en root, et le contenu peut ressortir via `logs`.
2. **Autres leviers non filtrés** : `userns_mode: host`, `uts`, `cgroup_parent`, `sysctls`, `volumes_from`, `pid: service:`. Une liste d'autorisation de champs vaut mieux qu'une liste d'interdits.
3. **Symlink à l'intérieur du projet** : le filtre compare des chaînes (`startswith($dir + "/")`) ; un lien `projet/lien -> /` ou un `..` dans la source peut passer. Résoudre les chemins (`realpath`) avant comparaison.
4. **TOCTOU sur le répertoire** : `$BASE_DIR` appartient à `plat-*`, qui peut renommer ou remplacer `$DIR` entre le test `! -L` et le `cd`. Seul le dernier composant est testé. Piste : `$BASE_DIR` propriété de root.
5. **Fichier `.env` du projet** lu par `docker compose config` en root (variables `COMPOSE_*`, interpolation) : contenu contrôlé par l'utilisateur.
6. **Bootstrap en conteneur** : `systemctl reload ssh` échoue sans systemd (cas probable en conteneur jetable) ; avec `set -e`, le script s'arrête avant le wrapper et le sudoers. Prévoir `service ssh reload` ou un conteneur systemd.
7. **Arguments manquants** : `--env` sans valeur avec `set -u` donne « unbound variable » (code 1), pas le code 64 attendu.
8. **`Match User plat-*` dans `sshd_config.d`** : vérifier que la portée s'arrête à la fin du fichier inclus sur la version d'OpenSSH visée.
9. **sudoers `*`** : les arguments au-delà de `ACTION PROJECT` sont ignorés par le wrapper ; à confirmer par le cas 4.

## Changements de conception à retenir (sous réserve de l'essai)

- Liste d'autorisation de champs Compose au lieu d'une liste d'interdits, y compris `secrets`, `configs`, `env_file`, volumes nommés et `driver_opts`.
- Résoudre les chemins avant comparaison ; répertoires parents propriété de root.
- Rendre `up` à partir du seul fichier vérifié (déjà prévu), sans lire `.env` ni `env_file` hors projet.
- Bootstrap testable sans systemd.

## Pour terminer l'essai

Démarrer OrbStack, conteneur Debian avec `openssh-server sudo jq docker-compose-plugin`, y copier les extraits de la spec, exécuter les six cas en notant commande et sortie réelle. Le propriétaire relit avant fermeture du ticket.
