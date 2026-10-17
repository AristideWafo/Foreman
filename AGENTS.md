# AGENTS.md — consignes pour les agents de code

Ce fichier s'adresse aux agents de code (Claude Code, etc.) et aux humains.
`CLAUDE.md` pointe ici. En cas de doute, ces règles priment.

## Commandes (interface unique : le `Makefile`)

| Commande | Rôle |
| --- | --- |
| `make install` | Installe backend (uv) et frontend (pnpm) |
| `make check` | Rapide : lint, format, typage, couches. À lancer avant chaque commit |
| `make check-full` | `check` + tests + build front |
| `make check-imports` | Contrats de couches (import-linter) |
| `make fmt` | Formate le code |
| `make test` | Tests backend et frontend |

Ne contournez pas le `Makefile` : la CI appelle les mêmes cibles.

## Architecture : couches (dépendances vers le bas uniquement)

```
surfaces (web API, cli)  ->  bootstrap  ->  tools, integrations  ->  core, infra  ->  config
```

- `config` est une feuille : il n'importe aucun paquet du projet.
- `core` définit les interfaces (ports) ; `infra` les implémente. `core` n'importe jamais `infra`.
- `tools` et `integrations` sont pairs : ils ne s'importent pas.
- `bootstrap` est la seule racine de composition (seul endroit où `tools` et `integrations` coexistent).
- Les surfaces n'exécutent jamais de logique d'agent : elles appellent le `TurnService`.
- Pas de dossier fourre-tout (`utils/`, `common/`, `helpers/`, `services/`, `vendors/`).
- `deploy/` n'est jamais importé par l'application.

Toute exception à ces règles est listée dans `docs/DEBT.md` et figée par un test. Ne l'allongez pas sans accord.

## Sécurité (non négociable)

- Aucun secret, clé ou jeton dans le dépôt, les logs, les prompts ou les tests.
- Aucun détail d'exception ne sort vers l'extérieur : log côté serveur, message générique côté client.
- Les agents ne créent ni ne modifient `SKILL.md` ni le prompt système : ils *proposent*, un humain relit.
- Pas de routage par regex ou mots-clés autour de l'agent : le modèle décide, la Tool Gateway limite.
- Les clients LLM sont sans état entre requêtes ; la configuration passe par le contexte.
- Les appels bloquants (SSH, sous-processus) ne tournent jamais dans la boucle asynchrone.

## Tests

- Peu de tests, à fort signal : sécurité/autorisation, concurrence/arrêt, frontières de couches, régressions.
- Interdit : un test qui vérifie seulement qu'un mock a été appelé.
- Fakes nommés (classes), pas de lambdas en ligne. Un test instable est un vrai bug : on le corrige, on ne le relance pas.
- Les tests de migration utilisent un vrai PostgreSQL.

## Workflow Git

- Branches courtes depuis `main`, PR petites. Pour une grosse fonctionnalité : PR empilées.
- Commits conventionnels (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `ci:`).
- Après chaque push : vérifiez le statut des checks (`gh pr checks`), corrigez la cause racine, surveillez `main` après fusion.
- Une modification de `gateway/`, `policy/`, `migrations/` ou `.github/workflows/` exige la relecture du propriétaire (CODEOWNERS).
- Pas de couche de compatibilité : quand un module est remplacé, l'ancien est supprimé dans le même changement.

## Ajouter une intégration

Ordre fixe : normalisation de la config → outils → docs → tests → `make verify-integrations`.
Détail dans `docs/adding-an-integration.md`.
