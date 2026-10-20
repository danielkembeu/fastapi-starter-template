"""Pagination, tri et filtres communs à tous les endpoints de liste.

Contrat unique, documenté dans `docs/PAGINATION.md` :

- paramètres `limit` (1..100, défaut 20) et `offset` (>= 0) ;
- tri par le paramètre `sort` (liste blanche par endpoint, `-champ` = décroissant),
  toujours départagé par `id` pour que deux pages successives ne se chevauchent pas ;
- réponse enveloppée : `{"items": [...], "total": N, "limit": L, "offset": O, "has_more": bool}`.

Aucune requête de liste ne doit renvoyer une table entière : c'est ce qui rend l'API
résistante à la montée en charge.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select
from sqlmodel.sql.expression import SelectOfScalar

from app.core.errors import AppError, ErrorCode

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class PageParams(BaseModel):
    limit: int
    offset: int


class PageQuery(BaseModel):
    """Paramètres de pagination communs. Chaque modèle de filtres en hérite : FastAPI ne développe
    un modèle de paramètres de requête (dans Swagger) que s'il est le SEUL de la route.
    """

    limit: int = Field(
        default=DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description=f"Nombre maximal d'éléments (1 à {MAX_LIMIT}).",
    )
    offset: int = Field(default=0, ge=0, description="Nombre d'éléments à sauter.")

    @property
    def page(self) -> PageParams:
        return PageParams(limit=self.limit, offset=self.offset)


class Page[T](BaseModel):
    """Enveloppe de réponse de tous les endpoints de liste."""

    items: list[T]
    total: int = Field(description="Nombre total d'éléments correspondant aux filtres.")
    limit: int
    offset: int
    has_more: bool = Field(description="Vrai s'il reste des éléments après cette page.")


class DateRangeFilter(BaseModel):
    """Intervalle de dates (bornes incluses) appliqué à la date de création."""

    created_from: datetime | None = Field(default=None, description="Créé à partir de (inclus).")
    created_to: datetime | None = Field(default=None, description="Créé jusqu'à (inclus).")


def apply_date_range(
    stmt: SelectOfScalar,
    column: Any,
    created_from: datetime | None,
    created_to: datetime | None,
) -> SelectOfScalar:
    if created_from and created_to and created_from > created_to:
        raise AppError(400, ErrorCode.INVALID_DATE_RANGE, "created_from doit précéder created_to")
    if created_from:
        stmt = stmt.where(column >= created_from)
    if created_to:
        stmt = stmt.where(column <= created_to)
    return stmt


def apply_sort(
    stmt: SelectOfScalar,
    sort: str,
    columns: Mapping[str, Any],
    tiebreaker: Any,
) -> SelectOfScalar:
    """Applique `sort` (`champ` ou `-champ`) limité aux colonnes autorisées de `columns`."""
    descending = sort.startswith("-")
    name = sort.lstrip("-")
    column = columns.get(name)
    if column is None:
        raise AppError(400, ErrorCode.INVALID_SORT, f"Tri non supporté : {sort}")
    ordered = column.desc() if descending else column.asc()
    return stmt.order_by(ordered, tiebreaker.desc() if descending else tiebreaker.asc())


def like_pattern(term: str) -> str:
    """Motif LIKE sûr : neutralise les jokers de l'utilisateur."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def paginate(
    session: Session,
    stmt: SelectOfScalar,
    params: PageParams,
    *,
    options: Sequence[Any] = (),
) -> dict[str, Any]:
    """Exécute `stmt` (déjà filtrée et triée) par pages, avec le total.

    `options` accueille les `selectinload(...)` : ils sont appliqués à la requête de données
    mais pas au comptage.
    """
    total = session.exec(select(func.count()).select_from(stmt.order_by(None).subquery())).one()
    data_stmt = stmt.options(*options).limit(params.limit).offset(params.offset)
    items = list(session.exec(data_stmt).all())
    return {
        "items": items,
        "total": total,
        "limit": params.limit,
        "offset": params.offset,
        "has_more": params.offset + len(items) < total,
    }
