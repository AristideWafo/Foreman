# CI

| Workflow | Déclencheur | Rôle |
| --- | --- | --- |
| `ci.yml` | PR, `main` | Jobs parallèles : lint/typage/couches, tests backend, frontend, contrat API. Check requis : **CI OK** |
| `security.yml` | PR, `main`, hebdo | CodeQL (main/hebdo), revue des dépendances (PR), `pip-audit`, `pnpm audit`, gitleaks |
| `build.yml` | `main`, tags `v*` | Image construite une fois, scan Trivy, signature, SBOM, provenance |
| `deploy.yml` | après Build, manuel | Staging auto ; production manuelle avec relecteurs |
| `release-please.yml` | `main` | PR de version et changelog |
| `evals.yml` | hebdo, manuel | Scénarios avec le vrai modèle, jamais bloquants |

## Règles

- Actions tierces épinglées par SHA de commit (le tag est en commentaire) ; Dependabot les met à jour.
- `permissions: contents: read` par défaut, élargi par job.
- Concurrence : les exécutions obsolètes sont annulées (sauf build et deploy).
- Pas de couverture sur les PR ; si elle est utile, elle est produite sur `main`.
- Après chaque push : `gh pr checks`, corriger la cause racine, surveiller `main` après fusion.
- Un test instable est un bug, on ne le relance pas.

## À brancher quand la persistance arrive

Service PostgreSQL dans `backend-tests` et job de test des migrations (voir `PERSISTENCE.md`).
