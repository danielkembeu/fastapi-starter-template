# Contribuer

Bienvenue. Ce dépôt a des exigences élevées de **sécurité, de tests et de fiabilité** : elles sont appliquées
automatiquement, ce qui vous évite de les deviner. Que vous soyez une personne ou un assistant de code, les règles
sont les mêmes : [`AGENTS.md`](AGENTS.md).

## Mise en place (une fois)

```bash
python -m venv env && source env/bin/activate     # le venv doit être ACTIF quand vous committez
make install && make up
cp .env.example .env.local                         # renseigner SECRET_JWT
make migrate && make hooks
make check                                         # doit être vert avant de commencer
```

## Le flux de travail

1. **Branche** depuis `main` : `feature/<sujet>`, `fix/<sujet>`, `docs/<sujet>`.
2. **Écrire le test d'abord** quand c'est un bug ; pour une fonctionnalité, le test et le code ensemble.
3. **Coder** en suivant [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) et, pour une ressource,
   [`docs/AJOUTER_UN_MODULE.md`](docs/AJOUTER_UN_MODULE.md).
4. **Vérifier** : `make check`. Si le schéma change : `make rev m="…"`, relire la migration, `make drift`, `make test-pg`.
5. **Committer** : les hooks tournent (secrets, lint, format). Ne jamais utiliser `--no-verify`.
6. **Pousser** : les hooks de push lancent mypy, la référence d'API et les tests (~1 min).
7. **Ouvrir une PR** avec le modèle fourni ; la CI doit être verte. Une PR = un sujet, petite, relisible.

## Messages de commit

Impératif, explicatif, en français : le **pourquoi** avant le comment.

```text
Verrouiller le compte après N échecs de connexion

Sans limite par compte, la limite par IP ne protège pas d'une attaque distribuée.
Le verrou expire seul ; la réactivation par un administrateur est prévue.
```

## Ce qui fait refuser une contribution

- `make check` rouge, ou un hook contourné.
- Un comportement sans test, ou un test qui ne peut pas échouer.
- Une route sans permission déclarée, sans trace d'audit, ou non paginée (les garde-fous le détectent).
- Une migration non relue, non rejouable, ou modifiée après avoir été poussée.
- Un secret, un identifiant de base réel, un `print()`, un `datetime.now()`.
- Une protection affaiblie « pour faire passer ».

## Signaler une faille

Ne pas ouvrir de ticket public. Contacter les mainteneurs en privé avec les étapes pour reproduire.
