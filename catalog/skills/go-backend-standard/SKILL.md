---
name: go-backend-standard
version: 1
status: draft
description: Appliquer le standard de l'équipe pour un service backend Go (structure, configuration, journaux, santé).
tools: []
---

# Objectif
Garder les services backend Go de l'équipe homogènes, du boilerplate au déploiement.

# Instructions
1. Partir du boilerplate `go-api` (`referentiels/boilerplates.yaml`), sans en retirer la structure.
2. Exposer une route `/healthz` qui répond 200 sans dépendance externe, utilisée par le health check.
3. Lire la configuration dans l'environnement (principes 12-factor), jamais dans un fichier versionné.
4. Écrire des journaux structurés sur la sortie standard, sans donnée personnelle ni secret.
5. Écouter sur le port annoncé par le fichier Compose et s'arrêter proprement sur SIGTERM.

# Règles
- Ne jamais écrire un secret, un jeton ou un mot de passe dans le code, les journaux ou un exemple.
- Ne jamais ajouter une dépendance sans la signaler dans le plan.
- Si la stack demandée n'est pas dans le référentiel des boilerplates, poser la question.

# Résultat attendu
Un dépôt qui démarre, répond sur `/healthz` et se déploie par le Skill `docker-staging-deploy`.
