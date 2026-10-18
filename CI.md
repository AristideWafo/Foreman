# CI

| Workflow | Déclencheur | Rôle |
| --- | --- | --- |
| `ci.yml` | PR, `prod` | Jobs parallèles : lint/typage/couches, tests backend, frontend, contrat API. Check requis : **CI OK** |
| `security.yml` | PR, `prod`, hebdo | CodeQL (prod/hebdo), revue des dépendances (PR), `pip-audit`, `pnpm audit`, gitleaks |
| `build.yml` | `prod`, tags `v*` | Image construite une fois, scan Trivy, signature, SBOM, provenance |
| `deploy.yml` | après Build sur `prod`, manuel | Déploiement automatique vers l'environnement `env-perso` ; redéploiement manuel d'un SHA |
| `release-please.yml` | `prod` | PR de version et changelog |
| `evals.yml` | hebdo, manuel | Scénarios avec le vrai modèle, jamais bloquants |

## Règles

- Actions tierces épinglées par SHA de commit (le tag est en commentaire) ; Dependabot les met à jour.
- `permissions: contents: read` par défaut, élargi par job.
- Concurrence : les exécutions obsolètes sont annulées (sauf build et deploy).
- Pas de couverture sur les PR ; si elle est utile, elle est produite sur `prod`.
- Après chaque push : `gh pr checks`, corriger la cause racine, surveiller `prod` après fusion.
- Un test instable est un bug, on ne le relance pas.

## À brancher quand la persistance arrive

Service PostgreSQL dans `backend-tests` et job de test des migrations (voir `PERSISTENCE.md`).
