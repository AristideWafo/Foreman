# Architecture

## Couches

```
surfaces (web API, cli)  ->  bootstrap  ->  tools, integrations  ->  core, infra  ->  config
```

| Couche | Rôle | Peut importer |
| --- | --- | --- |
| `surfaces` | API HTTP/SSE, CLI, webhooks entrants. Aucune logique d'agent. | `bootstrap`, `core`, `config` |
| `bootstrap` | Racine de composition : profils (`web`, `cli`, `worker`, `eval`), ordre de démarrage fixe. | tout ce qui est en dessous |
| `tools` | Outils neutres vis-à-vis des fournisseurs, `tools/crossvendor` pour les combinaisons. | `core`, `config` |
| `integrations` | Un paquet par fournisseur (config, vérification, client, outils, identifiants). | `core`, `config` |
| `core` | Domaine, `TurnService`, boucle d'agent, budgets, ports (interfaces). | `config` |
| `infra` | Implémentations des ports : base de données, queue, secrets, SSH, runner. | `core` (interfaces), `config` |
| `config` | Constantes, noms de variables d'environnement. Feuille. | rien |

Règles : pairs sans import mutuel (`tools` ↔ `integrations`, `surfaces` ↔ cli/web entre eux) ;
`core` définit les interfaces, `infra` les implémente, jamais l'inverse.

## Flux d'un tour

1. Une surface reçoit la demande et la transmet au `TurnService`.
2. Chaîne commune : identité → droits du demandeur → approbation si requise.
3. La boucle d'agent appelle le fournisseur de modèle (`Provider`) et les outils via la Tool Gateway.
4. Budgets : appels, temps, coût et tokens de contexte (logs injectés).
5. Événements diffusés en SSE ; actions journalisées dans l'audit.

## Décisions

Les décisions structurantes sont consignées dans `docs/adr/`.
