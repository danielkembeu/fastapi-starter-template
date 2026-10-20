# CLAUDE.md

Les règles de ce dépôt sont dans **[`AGENTS.md`](AGENTS.md)** — c'est la source unique, valable pour tous les
assistants de code et pour les humains. Les lire en entier avant de modifier quoi que ce soit.

Rappel minimal : `make check` doit être vert avant chaque commit ; tout comportement est testé, refus compris ;
architecture `router → service → models` ; Alembic seul maître du schéma ; `utc_now()` et jamais `datetime.now()` ;
aucune base écrite sans avoir vérifié sa cible. Cadre complet : [`docs/TRAVAILLER_AVEC_UNE_IA.md`](docs/TRAVAILLER_AVEC_UNE_IA.md).
