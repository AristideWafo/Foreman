# Ajouter une intégration

Ordre fixe :

1. **Config** : normalisation et vérification dans `integrations/<vendor>/config.py`.
2. **Client et identifiants** : `integrations/<vendor>/client.py`, jamais de secret en clair.
3. **Outils** : `integrations/<vendor>/tools/` (un seul fournisseur) ; combinaisons dans `tools/crossvendor`.
4. **Enregistrement** : dans `bootstrap/adapters.py`, seul endroit où le fournisseur est branché.
5. **Docs** : une page courte dans `docs/integrations/`.
6. **Tests** : un fake nommé par adaptateur, tests de sécurité/autorisation de la Tool Gateway.
7. **Vérification** : `make check`.

Règles : pas d'import entre `integrations` et `tools` ; entrant (webhooks) dans `surfaces`, sortant dans `integrations` ;
la logique propre à un fournisseur partagée par deux fonctions sort dans son propre module.
