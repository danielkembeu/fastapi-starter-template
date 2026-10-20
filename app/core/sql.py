"""Petits utilitaires SQLAlchemy/SQLModel qui contournent les limites du typage statique."""

from typing import Any

from sqlalchemy.orm import selectinload


def eager(*relationships: Any) -> tuple[Any, ...]:
    """Chargement anticipé (`selectinload`) de relations de modèles SQLModel.

    Les relations y sont typées `Optional[X]` / `list[X]`, ce que `selectinload` refuse côté
    typage alors que c'est correct à l'exécution : ce helper centralise la contournement.
    """
    return tuple(selectinload(relationship) for relationship in relationships)
