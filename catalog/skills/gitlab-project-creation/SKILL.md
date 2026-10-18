---
name: gitlab-project-creation
version: 1
status: draft
description: Choisir le groupe GitLab, nommer les dépôts front et back et les initialiser depuis le boilerplate de l'équipe.
tools: [gitlab.create_group, gitlab.create_project]
---

# Objectif
Créer la structure GitLab d'un projet selon les conventions de l'équipe.

# Instructions
1. Lire `referentiels/gitlab-groups.yaml` pour trouver le groupe parent de l'équipe.
2. Planifier un groupe `<slug>` sous ce parent, puis deux sous-groupes `frontend` et `backend`.
3. Planifier un dépôt par sous-groupe depuis le boilerplate correspondant à la stack
   (`referentiels/boilerplates.yaml`) : `<slug>-api` dans `backend`, `<slug>-web` dans `frontend`.
4. Réutiliser les mêmes paramètres pour une étape rejouée : la création lit d'abord, puis crée.
5. Présenter le plan au développeur avant toute création.

# Règles
- Ne jamais choisir un groupe au hasard : si le référentiel est ambigu, poser la question.
- Ne jamais écrire hors du groupe racine de la plateforme.
- Ne jamais afficher ni demander la valeur d'un secret.

# Résultat attendu
URL des groupes et dépôts, statut de chaque étape.
