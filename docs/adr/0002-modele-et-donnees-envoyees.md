# ADR 0002 — Modèle LLM et données envoyées

**Statut** : proposé (relecture du propriétaire en attente — ticket #64)

## Contexte

La page d'administration « Intégrations » (jalon 17) permet de saisir la clé du fournisseur LLM et de
choisir le modèle. Il faut fixer ce qui part chez le fournisseur, ce qui n'en part jamais, et qui gère la clé.

## Décisions

### Fournisseur, modèle et budget

- **Anthropic seul** pour l'instant. Pas d'abstraction multi-fournisseurs au-delà du port `Provider` existant.
- Une **clé LLM globale à l'organisation**, saisie dans l'interface, **gérée par `org_admin` seul**. Les autres
  rôles ne peuvent ni la lire, ni la remplacer, ni la supprimer ; elle n'est jamais renvoyée par l'API
  (seulement « présente / absente »). Stockage : magasin de secrets chiffré (#256).
- Le **modèle** se choisit dans une **liste déclarée dans le code** (liste déroulante). Chaque entrée porte
  son identifiant et son tarif, affichés à l'admin. **Pas de repli automatique** vers un autre modèle : si le
  modèle choisi est indisponible, l'erreur est remontée. Ajouter un modèle = changer le code, relu en PR.
- **Budget en EUR**, converti depuis les tarifs (USD) avec un **taux fixe** déclaré dans le code et affiché.
  Le taux n'est pas lu en ligne : le budget reste prévisible et testable. Le taux se révise à la main.

### Ce qui part chez Anthropic

- Les **messages du chat**, après masquage par `redact.mask_text`.
- Les **extraits de Skills et de référentiels** nécessaires au tour.
- Les **sorties d'outils filtrées** (passées par la même redaction que le journal).

### Ce qui ne part jamais

- Jetons et clés (y compris la clé LLM elle-même hors en-tête d'authentification).
- Logs bruts (sorties complètes de commandes, Ansible, SSH).
- Valeurs de variables (seuls les noms et les types sont décrits au modèle).
- **Noms d'hôtes internes** : remplacés par des alias stables avant l'envoi, ré-associés à la réponse.

Un test sur la frontière d'envoi vérifie ces catégories ; toute nouvelle source de contenu passe par la même
redaction avant d'atteindre le `Provider`.

### Conservation chez le fournisseur

**30 jours par défaut** (politique standard du fournisseur, sans option de rétention zéro activée). À revérifier auprès des conditions commerciales du fournisseur (entraînement, durée) avant la mise en
production. Une rétention plus courte demandera un accord dédié et un nouvel ADR.

### Logs bruts

- **Lieu** : base PostgreSQL du contrôleur, jamais envoyés au fournisseur.
- **Durée** : durée de rétention fixée avec la politique du journal (à préciser dans la config, valeur par
  défaut proposée : 30 jours, comme chez le fournisseur).
- **Accès** : réservé à `org_admin` par défaut ; les autres rôles ne voient que la version masquée.
  Décision détaillée : ticket #70 (visibilité par rôle), qui s'appuie sur cet ADR.

## Conséquences

- Le contrôleur est la seule frontière de confiance : la redaction est testée côté contrôleur, pas déléguée.
- Changer de modèle ou de taux est un changement de code relu, jamais un réglage libre.
- La perte de la clé maître du magasin de secrets oblige à ressaisir la clé LLM (voir #256).
- Coût : le masquage et l'aliasing des hôtes peuvent dégrader la qualité des réponses du modèle ; à mesurer
  dans l'évaluation.
