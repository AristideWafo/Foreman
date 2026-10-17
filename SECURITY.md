# Sécurité

## Signaler une vulnérabilité

Ne créez pas d'issue publique. Utilisez les « Security advisories » privés du dépôt GitHub
ou écrivez au propriétaire du dépôt.

## Principes de conception

- **Moindre privilège** : l'agent n'agit que par la Tool Gateway, qui applique la politique d'accès.
- **Aucun secret dans le code ni dans les logs** ; secrets chiffrés au repos (age/sops puis Vault).
- **Erreurs opaques vers l'extérieur** : détails uniquement dans les logs serveur.
- **Approbation humaine** pour les actions à effet de bord définies par la politique.
- **Traçabilité** : chaque action d'outil est journalisée dans l'audit.
- **Chaîne d'approvisionnement** : actions CI épinglées par SHA, images signées, SBOM, analyse des dépendances.
