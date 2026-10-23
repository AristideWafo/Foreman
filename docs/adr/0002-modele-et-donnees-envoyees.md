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

### Lectures GitLab envoyées au modèle

- Les résultats des outils de lecture GitLab (listes, détails, **contenu de fichier**) partent chez le fournisseur
  après `mask_for_model` et aliasing, comme les autres sorties d'outils.
- Le contenu d'un fichier lu est **borné à 480 caractères** (la gateway coupe chaque chaîne à 500) et masqué ; `.env`, clés, fichiers d'identifiants et binaires sont refusés avant
  lecture.
- Il n'est **jamais placé dans un message `user`** : il voyage dans un bloc `tool_result`
  `{"tool", "untrusted_data"}`, donnée non fiable que le modèle ne doit pas exécuter comme une consigne.

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

### Diagnostic des échecs sans logs bruts

Sans logs bruts, le modèle ne juge pas une action sur du texte libre : le compromis est couvert par
des couches, de la plus à la moins utile. Chacune réduit le besoin de la suivante.

1. **Diagnostic déclaré par l'outil.** L'outil renvoie un résultat typé : code d'erreur normalisé
   (`port_in_use`, `permission_missing`, `image_not_found`…), état attendu contre état observé, et une
   sonde de vérification après action. Le modèle raisonne sur ces champs, pas sur du texte libre. S'appuie
   sur `expects` / `strip_from_results` de `connector.yaml` (chargés mais pas encore appliqués, voir PR #264).
2. **Extrait ciblé.** En cas d'échec, seules les N dernières lignes pertinentes, ou la ligne qui matche un
   motif d'erreur connu, sont transmises, passées par `mask_text` puis `filter_logs`, de taille bornée.
3. **Masquage par liste d'autorisation.** Seuls les champs déclarés partent ; tout le reste est écarté,
   plutôt qu'une liste d'interdits qui laisse passer l'inconnu (#178).
4. **Aliasing stable.** Hôtes et valeurs internes deviennent des alias stables (`host-1`, `var-A`) : le
   modèle corrèle sans voir la valeur.
5. **Repli humain.** Sans code connu, le modèle ne devine pas : une carte « diagnostic requis » (via
   `ask_user`) montre le log brut à l'humain habilité (#70, qui voit les logs bruts).
6. **Mesure.** Dans les évaluations (#61), scénarios d'échec S3 à S9, indicateur « le modèle corrige
   l'erreur avec le seul extrait filtré ». Si trop bas, on enrichit l'outil (couche 1), jamais en envoyant
   le flux brut.

**Ce qu'on ne fait pas** : aucun envoi de logs bruts en repli ; le modèle ne demande pas lui-même plus de
logs sans validation humaine.

**Ordre recommandé** : couches 1, 2, 5, puis 6, puis 3 et 4.

## Conséquences

- Le contrôleur est la seule frontière de confiance : la redaction est testée côté contrôleur, pas déléguée.
- Changer de modèle ou de taux est un changement de code relu, jamais un réglage libre.
- La perte de la clé maître du magasin de secrets oblige à ressaisir la clé LLM (voir #256).
- Coût : le masquage et l'aliasing des hôtes peuvent dégrader la qualité des réponses du modèle ; à mesurer
  dans l'évaluation.
