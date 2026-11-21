# Porte de qualité foreman-eval

Issue : #352. Statut : **squelette**. La cible `make` et ses seuils existent ; le jeu de cas
n'est pas encore versionné ici et la porte n'est pas branchée en CI.

## Pourquoi

Le catalogue `catalog/evals/diagnostic-s3-s9.yaml` repose sur des réponses synthétiques. L'évaluation
live du 6 novembre 2026 (48 tours réels, dépôt `foreman-eval`) a trouvé des défauts que la CI ne
voyait pas : tours en échec sans message, inventaires tronqués, chiffres inventés. Avant cette porte,
aucun score de qualité n'était suivi d'une version à l'autre.

## Seuils

| Indicateur | Clé du rapport | Seuil |
| --- | --- | --- |
| Tours terminés (`completed`) | `completed_rate` | ≥ 0,95 |
| Honnêteté (aucune donnée non lue affirmée) | `honesty_rate` | = 1,0 |
| Pertinence moyenne (juge, sur 5) | `relevance_mean` | ≥ 3,5 |

Un indicateur absent fait échouer la porte.

## Utilisation

```sh
make eval-gate REPORT=chemin/vers/rapport.json   # code de sortie 1 sous un seuil
```

Le script (`backend/tests/quality_gate.py`) ne fait que lire un rapport déjà produit. Il n'appelle
aucun modèle.

## Étapes suivantes (non faites)

1. Versionner dans ce dépôt les cas de `foreman-eval/eval/dataset/cases/`, sans données réelles
   (hôtes et noms aliasés).
2. En CI : rejouer les cas avec les juges **déterministes** seulement (statut du tour, message présent,
   chiffres égaux aux `tool_call` du tour), produire le rapport, puis lancer `make eval-gate`.
3. Avant chaque déploiement : lancer le jeu live (`tools/run_live.sh`, juges LLM) hors CI et archiver le
   rapport avec la release. Les juges LLM ne tournent jamais en CI : ils coûtent de l'argent et ne sont
   pas reproductibles.
