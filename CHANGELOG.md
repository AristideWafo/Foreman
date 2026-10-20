# Changelog

## [0.17.0](https://github.com/AristideWafo/Foreman/compare/v0.16.0...v0.17.0) (2026-10-20)


### Features

* API d'administration des équipes, membres, rôles et invitations ([#224](https://github.com/AristideWafo/Foreman/issues/224)) ([d1f21a8](https://github.com/AristideWafo/Foreman/commit/d1f21a8be8c0ecf3a600360191e2720b3fc2c610))
* cloisonnement des projets par équipe ([#223](https://github.com/AristideWafo/Foreman/issues/223)) ([c3c8cae](https://github.com/AristideWafo/Foreman/commit/c3c8cae3588b8a9cffa15ce419ff397a6b7ffb9a))
* comptes, sessions, invitations et invariants admin ([#221](https://github.com/AristideWafo/Foreman/issues/221)) ([b64ce37](https://github.com/AristideWafo/Foreman/commit/b64ce37919ee662f9b825e818d5b835b4227a90f))
* **deploy:** mode session derrière Traefik, retrait du basicAuth ([#228](https://github.com/AristideWafo/Foreman/issues/228)) ([07ba988](https://github.com/AristideWafo/Foreman/commit/07ba988556198529bc1272d42bf46c0373ddf1a1))
* **deploy:** mode session derrière Traefik, retrait du basicAuth ([#228](https://github.com/AristideWafo/Foreman/issues/228)) ([639ab23](https://github.com/AristideWafo/Foreman/commit/639ab231a914093875f83bf3f6ff818d8e9e561f))
* **front:** page d'administration et sélecteur d'équipe ([#227](https://github.com/AristideWafo/Foreman/issues/227)) ([17c896d](https://github.com/AristideWafo/Foreman/commit/17c896d16da5f98d160acf703763adec74e16d3d))
* **front:** page d'administration et sélecteur d'équipe ([#227](https://github.com/AristideWafo/Foreman/issues/227)) ([da011c9](https://github.com/AristideWafo/Foreman/commit/da011c98cb1d224b0a9750a11bbd92816f829d67))
* mot de passe, sessions, CSRF et CLI admin ([#222](https://github.com/AristideWafo/Foreman/issues/222)) ([f476c82](https://github.com/AristideWafo/Foreman/commit/f476c82c71cbdf7f0f8f8dfb7a83f2f4b457087c))

## [0.16.0](https://github.com/AristideWafo/Foreman/compare/v0.15.0...v0.16.0) (2026-10-19)


### Features

* **approval:** balayage d'expiration des plans (S12, [#209](https://github.com/AristideWafo/Foreman/issues/209)) ([ee9370b](https://github.com/AristideWafo/Foreman/commit/ee9370be61e3672635f89f5a48a96bc5bbd0f69c))
* **approval:** balayage d'expiration des plans (S12) ([36f95d7](https://github.com/AristideWafo/Foreman/commit/36f95d7b370a1f3e354911a544378625346b29be))
* **contract:** invalidation du plan et statuts expired/invalidated (S12, [#208](https://github.com/AristideWafo/Foreman/issues/208)) ([c8f2fbb](https://github.com/AristideWafo/Foreman/commit/c8f2fbb8156dce20004f16e460c54c4b4d23dc72))
* **contract:** invalidation du plan et statuts expired/invalidated (S12) ([3c08c93](https://github.com/AristideWafo/Foreman/commit/3c08c937740acdfa966c3bdf298ac748beeb731f))
* **front:** carte plan invalidé ou expiré, Refaire le plan (S12, [#45](https://github.com/AristideWafo/Foreman/issues/45)) ([fca88a6](https://github.com/AristideWafo/Foreman/commit/fca88a6e60e7b33a62c3bc6472ae4b8140fa55b9))
* **front:** plan invalidé ou expiré, Refaire le plan (S12, [#45](https://github.com/AristideWafo/Foreman/issues/45)) ([f0fa92d](https://github.com/AristideWafo/Foreman/commit/f0fa92d0d27b5e1096323b4e835230742555b8c3))
* **plan:** base du plan foreman.plan/2 et contrôle avant approbation (S12, [#43](https://github.com/AristideWafo/Foreman/issues/43)) ([64fa566](https://github.com/AristideWafo/Foreman/commit/64fa5662d52bbe27c3d1caacc9cbd71660dfc18f))
* **plan:** base du plan foreman.plan/2 et invalidation avant approbation (S12, [#43](https://github.com/AristideWafo/Foreman/issues/43)) ([767aee0](https://github.com/AristideWafo/Foreman/commit/767aee0d926df92c0243b5971528fa74d45b8d99))
* **store:** invalidation du plan, expiration écrite, horloge injectée (PR-B S12) ([4cf98ca](https://github.com/AristideWafo/Foreman/commit/4cf98cabb7bf49890157c7281534ab428c226dd0))
* **store:** invalidation du plan, expiration écrite, horloge injectée (S12, [#43](https://github.com/AristideWafo/Foreman/issues/43)) ([3267505](https://github.com/AristideWafo/Foreman/commit/3267505c6b138f602ea5ce5c834ff9b195da894b))


### Bug Fixes

* **plan:** rejeu admin idempotent, historique d'un plan /1 illisible sans 500 (S12, [#43](https://github.com/AristideWafo/Foreman/issues/43)) ([97d887c](https://github.com/AristideWafo/Foreman/commit/97d887c1f3ded6287861a76d91168c5dd2120a7a))
* **store:** audit horodaté par now, raison d'invalidation validée, doc de retour arrière ([a5ac3ec](https://github.com/AristideWafo/Foreman/commit/a5ac3ecca623e16b322bc15812a8e739b0e30a17))

## [0.15.0](https://github.com/AristideWafo/Foreman/compare/v0.14.0...v0.15.0) (2026-10-19)


### Features

* **front:** relancer un plan dont l'exécution est bloquée ([a204f7b](https://github.com/AristideWafo/Foreman/commit/a204f7b0b72f0aed894dc82ecc3dd09070e1aec8))
* **front:** relancer un plan dont l'exécution est bloquée ([2b22261](https://github.com/AristideWafo/Foreman/commit/2b22261d19e523e7594e155a1f7a426ae9c5f73d))


### Bug Fixes

* **execution:** époque de l'adaptateur seul dans sa clé et dernier refus de l'étape bloquée ([dbaa868](https://github.com/AristideWafo/Foreman/commit/dbaa8685c21920291a36b63909cb1456db3a5295))
* **execution:** époque des faux + cause lisible d'une exécution bloquée ([2367355](https://github.com/AristideWafo/Foreman/commit/236735545a8b2c7e8cc60a4674ef8b364f82f1b1))
* **execution:** époque des faux dans la clé d'idempotence et cause lisible d'un blocage ([890a7b0](https://github.com/AristideWafo/Foreman/commit/890a7b06923ed6e829e22030d5b3dbfa2ee40ac8))

## [0.14.0](https://github.com/AristideWafo/Foreman/compare/v0.13.0...v0.14.0) (2026-10-19)


### Features

* **contrat:** ResourceRef.reused (champ facultatif, v1) ([75ca474](https://github.com/AristideWafo/Foreman/commit/75ca4742823247672b66fcd561ae54e82c15fd72))
* **contrat:** ResourceRef.reused (S11, PR-A) ([e66e8d4](https://github.com/AristideWafo/Foreman/commit/e66e8d454f386ce4f4bbe14f3bceb8b5c1f4b13a))
* **execution:** reprise d'une réservation orpheline (D3, PR-C) ([88718ed](https://github.com/AristideWafo/Foreman/commit/88718edf0920961f59db0d75be0bdae78d646453))
* **execution:** reprise d'une réservation orpheline (D3) ([7eba2e7](https://github.com/AristideWafo/Foreman/commit/7eba2e7dfd7ae04da2fe8f53d080e5fe8ec9939f)), closes [#188](https://github.com/AristideWafo/Foreman/issues/188)
* **front:** badge « déjà présente » sur les ressources réutilisées (S11, [#42](https://github.com/AristideWafo/Foreman/issues/42)) ([3530fd8](https://github.com/AristideWafo/Foreman/commit/3530fd8cde521f41919c4b8df0887b12d78a18b0))
* **front:** badge nom et rôle dans la barre latérale ([d0dbe3e](https://github.com/AristideWafo/Foreman/commit/d0dbe3e360eb6a35e4b376f1add5d253e1c367f0))
* **front:** badge nom et rôle de l'utilisateur dans la barre latérale ([6e7e744](https://github.com/AristideWafo/Foreman/commit/6e7e7446cc129a6f98e05ab183ca7d8fed13d3be))
* **front:** carte d'exécution S11, ressources déjà présentes ([91572c9](https://github.com/AristideWafo/Foreman/commit/91572c9ff4fe2cdde178df2284a5e65fd467bec4))
* **gateway:** réutiliser une ressource retrouvée au registre du projet (S11, PR-B) ([ab47144](https://github.com/AristideWafo/Foreman/commit/ab47144c7d0b8ec81802557ff8ee7188801a6316))
* **gateway:** une ressource retrouvée au registre du projet est réutilisée (S11) ([72c9892](https://github.com/AristideWafo/Foreman/commit/72c989237a6f461a5652d5f732ed8e608439f4f9))
* **registry:** identité environnement/slug des server_project ([#177](https://github.com/AristideWafo/Foreman/issues/177)) ([8a59ca6](https://github.com/AristideWafo/Foreman/commit/8a59ca6e6eb6dc143cfa2e6a52563ee7f097af9f))
* **registry:** identité environnement/slug des server_project ([#177](https://github.com/AristideWafo/Foreman/issues/177)) ([dabaf2a](https://github.com/AristideWafo/Foreman/commit/dabaf2a9c04d5ef000ac14a70459004949129712))


### Bug Fixes

* **catalog:** refuse un gabarit registry.external_id mal formé, docs 0004 ([b43f998](https://github.com/AristideWafo/Foreman/commit/b43f998ca02a3b751f2801de7b24449c85d72a07))
* **execution:** reprise d'une réservation refusée tant que le bail du propriétaire est vivant ([235099f](https://github.com/AristideWafo/Foreman/commit/235099feae6a3ffb3c82e40ba49f5a168b34ce99))
* **execution:** typage de la reprise, test de crash sans stratégie ([c9a3763](https://github.com/AristideWafo/Foreman/commit/c9a3763ec5428383410edd4c4a270ab0952cdedd))
* **front:** champ reused requis dans ResourceRef (types, tests, fixtures formatées) ([d3fd75b](https://github.com/AristideWafo/Foreman/commit/d3fd75b9f561c3a8f87b82f0a61132bc8ee05a74))
* **gateway:** la clé reused est ajoutée après la troncature de sortie ([537c6c7](https://github.com/AristideWafo/Foreman/commit/537c6c7420f5a2c240b33274b53f44d5afa112eb))

## [0.13.0](https://github.com/AristideWafo/Foreman/compare/v0.12.0...v0.13.0) (2026-10-19)


### Features

* **deploy:** FOREMAN_AUTH_PREFIX= retire le basicAuth de façon durable ([#182](https://github.com/AristideWafo/Foreman/issues/182)) ([0b0ec24](https://github.com/AristideWafo/Foreman/commit/0b0ec2462cd9b6afdb5247b1a5a9c36a38a02469))


### Bug Fixes

* **gitlab:** le faux GitLab ne réutilise plus d'identifiants après un redémarrage ([7a5b911](https://github.com/AristideWafo/Foreman/commit/7a5b911ac2bceb197634efcda242bc3df2472efd))
* le faux GitLab ne réutilise plus d'identifiants après un redémarrage ([1232f30](https://github.com/AristideWafo/Foreman/commit/1232f303bff6fb0ac3e6d3e2de28abdf5b8e4f06))

## [0.12.0](https://github.com/AristideWafo/Foreman/compare/v0.11.0...v0.12.0) (2026-10-19)


### Features

* approbation administrateur et rôle relu par la gateway (S4) ([2836695](https://github.com/AristideWafo/Foreman/commit/28366957540939f709c5fdf56320dfda002d0098))
* **front:** carte d'approbation administrateur (S4) ([408b8e7](https://github.com/AristideWafo/Foreman/commit/408b8e7b6adf9b46224f484078e5a8500483e1eb))
* matrice R1 à R10 et production (S4) ([073807b](https://github.com/AristideWafo/Foreman/commit/073807b88136a0a09fe2ea187d2e02f92006e1d3))
* rôles, authentification de développement et migration 0003 (S4) ([c853ae3](https://github.com/AristideWafo/Foreman/commit/c853ae3fa1ea2cc9caeca5c18e26ec02357c36e6))

## [0.11.0](https://github.com/AristideWafo/Foreman/compare/v0.10.0...v0.11.0) (2026-10-19)


### Features

* contrat S4 (carte d'approbation, rôles, /api/me, HealthResponse) ([59d8609](https://github.com/AristideWafo/Foreman/commit/59d86091da0d87b1e60365033772f3f5ae1baf22))
* contrat S4 (carte d'approbation, rôles, /api/me, HealthResponse) ([fbcb07b](https://github.com/AristideWafo/Foreman/commit/fbcb07bd0500b6bb90bf8a2a18de1c465dbbc533))


### Bug Fixes

* /healthz n'échoue plus sur une version hors motif ([9f409f8](https://github.com/AristideWafo/Foreman/commit/9f409f86a3d773a486cccb629a9c0d21d8b41aad))

## [0.10.0](https://github.com/AristideWafo/Foreman/compare/v0.9.0...v0.10.0) (2026-10-19)


### Features

* enregistrement S2 et fixture des cartes de clarification ([4fdf8be](https://github.com/AristideWafo/Foreman/commit/4fdf8be5dff42d7dc33e6fa236265f69087def85))
* **front:** carte de clarification (S2) ([cc38b98](https://github.com/AristideWafo/Foreman/commit/cc38b98820f6a74c94fbc78b72db20e53cca1e98))
* **front:** carte de clarification (S2) ([8aabcea](https://github.com/AristideWafo/Foreman/commit/8aabcea811280e8f7c8e08bc763b77255822dbfa))
* **front:** composants shadcn toggle et toggle-group ([7d198a4](https://github.com/AristideWafo/Foreman/commit/7d198a4d0deef7aadfd9ee5798a5e2170a3caef5))

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
