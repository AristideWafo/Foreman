# Tests

Peu de tests, à fort signal. Voir `AGENTS.md`.

| Dossier / fichier | Contenu |
| --- | --- |
| `test_structure.py` | Garde-fous de structure (dossiers fourre-tout, exceptions de couche figées) |
| `test_*.py` | Unitaires avec fakes nommés |
| `e2e/` | Scénarios `S1`…`S12` avec adaptateurs simulés et réponses de modèle rejouées (à venir) |

Convention : `e2e/test_s<NN>_<sujet>.py`, un scénario par fichier, fakes en classes nommées.
Les évals avec le vrai modèle vivent à part (`evals.yml`) et ne bloquent jamais une PR.
