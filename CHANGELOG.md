# Changelog

## [0.9.0](https://github.com/AristideWafo/Foreman/compare/v0.8.0...v0.9.0) (2026-10-18)


### Features

* **catalog:** schéma de projet et règle ask_user dans les Skills ([9556380](https://github.com/AristideWafo/Foreman/commit/955638030d904e0401bb1b51df0afc0466d401fd))
* clarification par ask_user, historique au Provider, route de réponse (PR-D, S3) ([ccfe10e](https://github.com/AristideWafo/Foreman/commit/ccfe10eba73e55cca7b7ffc279fab068e78739fe))
* clarification par ask_user, historique au Provider, route de réponse réelle ([1c100cc](https://github.com/AristideWafo/Foreman/commit/1c100ccf639b37e715292a00581739de3b0c149e)), closes [#33](https://github.com/AristideWafo/Foreman/issues/33) [#157](https://github.com/AristideWafo/Foreman/issues/157)
* **contrat:** carte et route de clarification (S3, route en 501) ([3e152af](https://github.com/AristideWafo/Foreman/commit/3e152af017fe148bc94f3ff7c00ba9300da2f355)), closes [#156](https://github.com/AristideWafo/Foreman/issues/156)
* **contrat:** carte et route de clarification (S3) ([7bef1a4](https://github.com/AristideWafo/Foreman/commit/7bef1a4b403f9c7a9c2c3858c9a0b50bc41ffc85))
* **front:** badge Mode mémoire ([a1a6b8a](https://github.com/AristideWafo/Foreman/commit/a1a6b8acc3d4e3f4016fcf9a156cb2ae36ed978f))
* **front:** badge Mode mémoire en pied de barre latérale ([3d3b951](https://github.com/AristideWafo/Foreman/commit/3d3b95120a8675567053e6d7e07c769ce88e9812)), closes [#155](https://github.com/AristideWafo/Foreman/issues/155)
* journal d'événements persisté en PostgreSQL (migration 0002) ([7131fa7](https://github.com/AristideWafo/Foreman/commit/7131fa7a31fb8541432ba37e127c655223c64ebc)), closes [#154](https://github.com/AristideWafo/Foreman/issues/154)
* journal d'événements persisté en PostgreSQL (PR-A, [#154](https://github.com/AristideWafo/Foreman/issues/154)) ([f250ff5](https://github.com/AristideWafo/Foreman/commit/f250ff56b5461c2c375fdef74de33a7896337be9))

## [0.8.0](https://github.com/AristideWafo/Foreman/compare/v0.7.0...v0.8.0) (2026-10-18)


### Features

* GET /api/projects, persistence dans /healthz, liste des projets lue en base ([#150](https://github.com/AristideWafo/Foreman/issues/150)) ([c188050](https://github.com/AristideWafo/Foreman/commit/c18805073f38566978d672655ca6790a362b0f3b))

## [0.7.0](https://github.com/AristideWafo/Foreman/compare/v0.6.0...v0.7.0) (2026-10-18)


### Features

* **front:** étapes et journaux repliables, carte sans bordure, icône d'attente ([ef19d53](https://github.com/AristideWafo/Foreman/commit/ef19d53af62d34a18725ed87fbbc66c39060f314))
* **front:** exécution dans la carte du plan, composants partagés, échelle typographique ([344b82a](https://github.com/AristideWafo/Foreman/commit/344b82ada679bf9c801b244682226999e3f3e026))
* **front:** trace repliable et animations séquentielles ([cdac1bc](https://github.com/AristideWafo/Foreman/commit/cdac1bc039d19bea04b50fd05ac8f04a09d0b30f))
* **front:** trace repliable et apparition séquentielle des composants ([8886fb8](https://github.com/AristideWafo/Foreman/commit/8886fb80202b230b413ee95c5a175634ca5e479d))

## [0.6.0](https://github.com/AristideWafo/Foreman/compare/v0.5.0...v0.6.0) (2026-10-18)


### Features

* **gateway:** Tool Gateway minimale et matrice de politique (R1, R2, R6) ([760d243](https://github.com/AristideWafo/Foreman/commit/760d243a128471eb967f7a21d7a76e31b2913134))
* **moteur:** exécution des plans approuvés, approbation et reprise (C2) ([5a6e90d](https://github.com/AristideWafo/Foreman/commit/5a6e90dc319a11b27347d10337e6bb3a5b730dca))
* **planning:** plan haché, persisté et carte enrichie ([#28](https://github.com/AristideWafo/Foreman/issues/28), [#30](https://github.com/AristideWafo/Foreman/issues/30)) ([067aef0](https://github.com/AristideWafo/Foreman/commit/067aef0309dfc7949872c0680fbc9b7a9d7746c0))


### Bug Fixes

* **persistance:** points de la revue indépendante (registre, audit, succès, borne) ([f50e00e](https://github.com/AristideWafo/Foreman/commit/f50e00e43348852a2b69cf76acf54cc6f1f0cae5))

## [0.5.0](https://github.com/AristideWafo/Foreman/compare/v0.4.0...v0.5.0) (2026-10-18)


### Features

* **persistance:** dépôts PostgreSQL et mémoire, migrations au démarrage, --with-db ([#26](https://github.com/AristideWafo/Foreman/issues/26), [#126](https://github.com/AristideWafo/Foreman/issues/126), [#127](https://github.com/AristideWafo/Foreman/issues/127)) ([79717c6](https://github.com/AristideWafo/Foreman/commit/79717c6974b27eb561d473982cfc5c7602841ff1))
* **persistance:** ports et dépôts PostgreSQL et mémoire, migrations au démarrage, --with-db ([#137](https://github.com/AristideWafo/Foreman/issues/137)) ([0c61608](https://github.com/AristideWafo/Foreman/commit/0c6160894c702a1f23cfb583363b71032791e45b))

## [0.4.0](https://github.com/AristideWafo/Foreman/compare/v0.3.0...v0.4.0) (2026-10-18)


### Features

* **adapters:** fakes nommés et modèle rejoué (P5) ([0bb6696](https://github.com/AristideWafo/Foreman/commit/0bb669665b0577b43224568be51e0e3474a5006e))
* **adapters:** fakes nommés GitLab, serveur et DNS, et modèle rejoué ([#29](https://github.com/AristideWafo/Foreman/issues/29)) ([0dad38d](https://github.com/AristideWafo/Foreman/commit/0dad38dd758d7027b9aa9c507dd99efcd61c33f1))
* **catalog:** Skills, référentiels, matrice minimale et définitions d'outils ([#30](https://github.com/AristideWafo/Foreman/issues/30), [#128](https://github.com/AristideWafo/Foreman/issues/128)) ([54ff935](https://github.com/AristideWafo/Foreman/commit/54ff9356e491654416327221b8c9c97e011aee17))
* **catalog:** Skills, référentiels, matrice minimale et outils (P4) ([817d169](https://github.com/AristideWafo/Foreman/commit/817d16973d5ad3d0bd227e95ced7d99b002101ed))
* **contrat:** contrat additif S1 (cartes plan et exécution, routes d'approbation) ([c9172eb](https://github.com/AristideWafo/Foreman/commit/c9172eb646d135847043898a266ddc81c5925829))
* **db:** migrations Alembic du schéma S1 et PostgreSQL en CI ([#25](https://github.com/AristideWafo/Foreman/issues/25)) ([#133](https://github.com/AristideWafo/Foreman/issues/133)) ([c2c8767](https://github.com/AristideWafo/Foreman/commit/c2c8767f8ae78d1b97040a7e4546d04d2a5ef9f4))
* **front:** cartes de plan et d'exécution, bouton « Valider le plan » ([#32](https://github.com/AristideWafo/Foreman/issues/32)) ([11bc49d](https://github.com/AristideWafo/Foreman/commit/11bc49d939d34847cfd300b8ff0e944de9ae0a09))
* **front:** cartes de plan et d'exécution, bouton « Valider le plan » ([#32](https://github.com/AristideWafo/Foreman/issues/32)) ([ec8c630](https://github.com/AristideWafo/Foreman/commit/ec8c6306aad24f8bd845c85ca7d4bbd9162daada))


### Bug Fixes

* **catalog:** corrections de la revue (playbooks, schémas fermés, matrice, lecture sûre) ([51360b1](https://github.com/AristideWafo/Foreman/commit/51360b1904629079baad834814686153febc7cc9))
* **contrat:** corrections de la revue indépendante (statuts de plan, approbation idempotente, ordre des événements) ([8568dbf](https://github.com/AristideWafo/Foreman/commit/8568dbf0f450f4abf0b1846c76700bc56fff39f5))

## [0.3.0](https://github.com/AristideWafo/Foreman/compare/v0.2.0...v0.3.0) (2026-10-18)


### Features

* add description ([67bc143](https://github.com/AristideWafo/Foreman/commit/67bc143e78e688a2a359dab8defaf40e306f1801))
* **backend:** squelette en couches avec contrats import-linter ([5a4e8ec](https://github.com/AristideWafo/Foreman/commit/5a4e8ec253ee9efb1902393224ca2cc39ab3f425))
* **back:** flux SSE des événements avec reprise ([d83fd14](https://github.com/AristideWafo/Foreman/commit/d83fd146e3a7812b81b7d0144cc9b9ddcc2ce584))
* **back:** flux SSE des événements avec reprise ([#19](https://github.com/AristideWafo/Foreman/issues/19)) ([6808e34](https://github.com/AristideWafo/Foreman/commit/6808e34801af7122012b29b07a0a5dfae79b8531))
* **back:** projets, messages et tour de l'agent en mémoire ([4762901](https://github.com/AristideWafo/Foreman/commit/476290174c4d74149e41b7a6eadadf3fd08219b4))
* **back:** projets, messages et tour de l'agent en mémoire ([#18](https://github.com/AristideWafo/Foreman/issues/18)) ([70bfda9](https://github.com/AristideWafo/Foreman/commit/70bfda9b565ba52a4eac5302e8f0c1e6b1cca82f))
* **contrat:** contrat v1 de l'API et des événements (routes en 501) ([a5cb5fc](https://github.com/AristideWafo/Foreman/commit/a5cb5fcdec45c022d40ecf97c213a0bcab25ee14))
* **contrat:** contrat v1 de l'API et des événements (S1 — P1) ([d902881](https://github.com/AristideWafo/Foreman/commit/d9028817bbc6348f2c23c11a9e0d5f615fd60fbf))
* **deploy:** authentification HTTP (basicAuth Traefik) obligatoire sur env-perso, /healthz public ([76b3fea](https://github.com/AristideWafo/Foreman/commit/76b3fea4c97c7853078ede4541ede8c80f2dc353))
* **deploy:** basicAuth Traefik obligatoire sur env-perso, /healthz public ([#106](https://github.com/AristideWafo/Foreman/issues/106)) ([adac9fb](https://github.com/AristideWafo/Foreman/commit/adac9fbc044625343fef761da2c50021fc6ff731))
* **deploy:** deploy-custom.sh et compose.custom.yaml pour un serveur Traefik ([c0f0b53](https://github.com/AristideWafo/Foreman/commit/c0f0b5327dab5ba7c901ed0a06d4de09e6603a94))
* **deploy:** deploy-custom.sh et compose.custom.yaml pour un serveur Traefik ([74bd20e](https://github.com/AristideWafo/Foreman/commit/74bd20e38d60a27b30466b1ac616881ef609fb9d))
* **front:** chat, flux d'événements et carte plan ([b28a7bb](https://github.com/AristideWafo/Foreman/commit/b28a7bb08f472471c030cd130a77cf73473e699a))
* **front:** chat, flux d'événements et carte plan ([#20](https://github.com/AristideWafo/Foreman/issues/20)) ([1834548](https://github.com/AristideWafo/Foreman/commit/18345485192fc2fcd84d5b20af61b7c4e2b4012c))
* **frontend:** squelette Vite + React + TS (Tailwind, Vitest, ESLint, Heroicons, Fontsource) ([6a4d7ed](https://github.com/AristideWafo/Foreman/commit/6a4d7ed7bfe941f48e3bf85fe7c20cf6a0f5b174))
* **front:** shadcn (Geist, Heroicons), double sidebar, accueil et conversation ([#114](https://github.com/AristideWafo/Foreman/issues/114)) ([cd1616d](https://github.com/AristideWafo/Foreman/commit/cd1616da87eac01a535a156b2ece52cac610689f))
* version visible et tags release-please compatibles avec le build ([#121](https://github.com/AristideWafo/Foreman/issues/121)) ([6b42853](https://github.com/AristideWafo/Foreman/commit/6b428532ebd6cdad3844ae0a0e4b6e9affa838a2))


### Bug Fixes

* **back:** délai du fournisseur, 404 sur /api inconnu avec la SPA, contrat Last-Event-ID aligné ([c9b7741](https://github.com/AristideWafo/Foreman/commit/c9b774156f889e654e58110f77344368d3bdcf96))
* **back:** plafonds d'abonnés SSE, arrêt borné, Last-Event-ID démesuré (revue indépendante) ([b8cb5d3](https://github.com/AristideWafo/Foreman/commit/b8cb5d32714d8d3cc393ce78c3ee787962753ac2))
* **build:** installer le paquet sans mode éditable dans l'image ([ccc47f4](https://github.com/AristideWafo/Foreman/commit/ccc47f498f0079e196295952f5f556ac7e133cbc))
* **build:** installer le paquet sans mode éditable dans l'image ([8545248](https://github.com/AristideWafo/Foreman/commit/85452489bef872d5be129eb56f3f1c87f3f0fdd3))
* **ci:** nom d'image GHCR en minuscules ([7ae49e2](https://github.com/AristideWafo/Foreman/commit/7ae49e2b271ce1a3bf1bbf527a8c5c9ec79017e8))
* **ci:** nom d'image GHCR en minuscules dans Build et Deploy ([0fc5fc9](https://github.com/AristideWafo/Foreman/commit/0fc5fc9f723fca756405cedaf998af0dc5ae032c))
* **ci:** port SSH configurable pour le déploiement ([1411db8](https://github.com/AristideWafo/Foreman/commit/1411db8625d5f093b1ddb406043917d7ce24b96f))
* **ci:** port SSH configurable pour le déploiement ([41976c7](https://github.com/AristideWafo/Foreman/commit/41976c7bdfc607e36fb62722631ce0c90d265e0f))
* **contrat:** corrections de la revue indépendante avant gel ([19636d8](https://github.com/AristideWafo/Foreman/commit/19636d8599ca545ad96779aac3795d9fdc6649b5))
* **contrat:** descriptions d'erreurs explicites (openapi.json identique en Python 3.12 et 3.13) ([00cc359](https://github.com/AristideWafo/Foreman/commit/00cc35930c0c8bdc942963a4f69de3f4e6ac2748))
* évals sans scénario encore, cible de vérification des intégrations ([c189302](https://github.com/AristideWafo/Foreman/commit/c1893022b728261c7fc16a47f2827dde1c1d7ee6))
* **front:** corrections de la revue indépendante (v, formes inattendues, 422, tests du réducteur) ([ebc1cf7](https://github.com/AristideWafo/Foreman/commit/ebc1cf7b1f5f386adc397554181ba18a212bba46))
* **front:** les étapes d'une carte sont numérotées à partir de 1 (contrat v1) ([0eb1914](https://github.com/AristideWafo/Foreman/commit/0eb191455148d9244ef4294466f2c0f842436b49))

## [0.2.0](https://github.com/AristideWafo/Foreman/compare/foreman-v0.1.0...foreman-v0.2.0) (2026-10-18)


### Features

* add description ([67bc143](https://github.com/AristideWafo/Foreman/commit/67bc143e78e688a2a359dab8defaf40e306f1801))
* **backend:** squelette en couches avec contrats import-linter ([5a4e8ec](https://github.com/AristideWafo/Foreman/commit/5a4e8ec253ee9efb1902393224ca2cc39ab3f425))
* **back:** flux SSE des événements avec reprise ([d83fd14](https://github.com/AristideWafo/Foreman/commit/d83fd146e3a7812b81b7d0144cc9b9ddcc2ce584))
* **back:** flux SSE des événements avec reprise ([#19](https://github.com/AristideWafo/Foreman/issues/19)) ([6808e34](https://github.com/AristideWafo/Foreman/commit/6808e34801af7122012b29b07a0a5dfae79b8531))
* **back:** projets, messages et tour de l'agent en mémoire ([4762901](https://github.com/AristideWafo/Foreman/commit/476290174c4d74149e41b7a6eadadf3fd08219b4))
* **back:** projets, messages et tour de l'agent en mémoire ([#18](https://github.com/AristideWafo/Foreman/issues/18)) ([70bfda9](https://github.com/AristideWafo/Foreman/commit/70bfda9b565ba52a4eac5302e8f0c1e6b1cca82f))
* **contrat:** contrat v1 de l'API et des événements (routes en 501) ([a5cb5fc](https://github.com/AristideWafo/Foreman/commit/a5cb5fcdec45c022d40ecf97c213a0bcab25ee14))
* **contrat:** contrat v1 de l'API et des événements (S1 — P1) ([d902881](https://github.com/AristideWafo/Foreman/commit/d9028817bbc6348f2c23c11a9e0d5f615fd60fbf))
* **deploy:** authentification HTTP (basicAuth Traefik) obligatoire sur env-perso, /healthz public ([76b3fea](https://github.com/AristideWafo/Foreman/commit/76b3fea4c97c7853078ede4541ede8c80f2dc353))
* **deploy:** basicAuth Traefik obligatoire sur env-perso, /healthz public ([#106](https://github.com/AristideWafo/Foreman/issues/106)) ([adac9fb](https://github.com/AristideWafo/Foreman/commit/adac9fbc044625343fef761da2c50021fc6ff731))
* **deploy:** deploy-custom.sh et compose.custom.yaml pour un serveur Traefik ([c0f0b53](https://github.com/AristideWafo/Foreman/commit/c0f0b5327dab5ba7c901ed0a06d4de09e6603a94))
* **deploy:** deploy-custom.sh et compose.custom.yaml pour un serveur Traefik ([74bd20e](https://github.com/AristideWafo/Foreman/commit/74bd20e38d60a27b30466b1ac616881ef609fb9d))
* **front:** chat, flux d'événements et carte plan ([b28a7bb](https://github.com/AristideWafo/Foreman/commit/b28a7bb08f472471c030cd130a77cf73473e699a))
* **front:** chat, flux d'événements et carte plan ([#20](https://github.com/AristideWafo/Foreman/issues/20)) ([1834548](https://github.com/AristideWafo/Foreman/commit/18345485192fc2fcd84d5b20af61b7c4e2b4012c))
* **frontend:** squelette Vite + React + TS (Tailwind, Vitest, ESLint, Heroicons, Fontsource) ([6a4d7ed](https://github.com/AristideWafo/Foreman/commit/6a4d7ed7bfe941f48e3bf85fe7c20cf6a0f5b174))
* **front:** shadcn (Geist, Heroicons), double sidebar, accueil et conversation ([#114](https://github.com/AristideWafo/Foreman/issues/114)) ([cd1616d](https://github.com/AristideWafo/Foreman/commit/cd1616da87eac01a535a156b2ece52cac610689f))


### Bug Fixes

* **back:** délai du fournisseur, 404 sur /api inconnu avec la SPA, contrat Last-Event-ID aligné ([c9b7741](https://github.com/AristideWafo/Foreman/commit/c9b774156f889e654e58110f77344368d3bdcf96))
* **back:** plafonds d'abonnés SSE, arrêt borné, Last-Event-ID démesuré (revue indépendante) ([b8cb5d3](https://github.com/AristideWafo/Foreman/commit/b8cb5d32714d8d3cc393ce78c3ee787962753ac2))
* **build:** installer le paquet sans mode éditable dans l'image ([ccc47f4](https://github.com/AristideWafo/Foreman/commit/ccc47f498f0079e196295952f5f556ac7e133cbc))
* **build:** installer le paquet sans mode éditable dans l'image ([8545248](https://github.com/AristideWafo/Foreman/commit/85452489bef872d5be129eb56f3f1c87f3f0fdd3))
* **ci:** nom d'image GHCR en minuscules ([7ae49e2](https://github.com/AristideWafo/Foreman/commit/7ae49e2b271ce1a3bf1bbf527a8c5c9ec79017e8))
* **ci:** nom d'image GHCR en minuscules dans Build et Deploy ([0fc5fc9](https://github.com/AristideWafo/Foreman/commit/0fc5fc9f723fca756405cedaf998af0dc5ae032c))
* **ci:** port SSH configurable pour le déploiement ([1411db8](https://github.com/AristideWafo/Foreman/commit/1411db8625d5f093b1ddb406043917d7ce24b96f))
* **ci:** port SSH configurable pour le déploiement ([41976c7](https://github.com/AristideWafo/Foreman/commit/41976c7bdfc607e36fb62722631ce0c90d265e0f))
* **contrat:** corrections de la revue indépendante avant gel ([19636d8](https://github.com/AristideWafo/Foreman/commit/19636d8599ca545ad96779aac3795d9fdc6649b5))
* **contrat:** descriptions d'erreurs explicites (openapi.json identique en Python 3.12 et 3.13) ([00cc359](https://github.com/AristideWafo/Foreman/commit/00cc35930c0c8bdc942963a4f69de3f4e6ac2748))
* évals sans scénario encore, cible de vérification des intégrations ([c189302](https://github.com/AristideWafo/Foreman/commit/c1893022b728261c7fc16a47f2827dde1c1d7ee6))
* **front:** corrections de la revue indépendante (v, formes inattendues, 422, tests du réducteur) ([ebc1cf7](https://github.com/AristideWafo/Foreman/commit/ebc1cf7b1f5f386adc397554181ba18a212bba46))
* **front:** les étapes d'une carte sont numérotées à partir de 1 (contrat v1) ([0eb1914](https://github.com/AristideWafo/Foreman/commit/0eb191455148d9244ef4294466f2c0f842436b49))
