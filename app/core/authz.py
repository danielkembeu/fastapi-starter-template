"""Autorisation : le seul endroit où l'on décide « qui a le droit de faire quoi ».

Trois questions distinctes, qu'un simple test d'égalité sur le rôle confondait :

- **Rôle** : qui es-tu ? (user, admin) — porté par `User.role`.
- **Permission** : quel type d'action ? — `Permission`, accordée par `ROLE_PERMISSIONS`.
- **Portée** : sur quelles lignes ? — `own` / `assigned` / `all`, matérialisée par les
  permissions `*_OWN`, `*_ASSIGNED`, `*_ALL` et par `ensure_owner_or_permission`.

Ajouter un rôle (ex. « support ») revient à ajouter une entrée dans `ROLE_PERMISSIONS`,
sans toucher un seul router ni service.

Limite à ne pas franchir : le RBAC répond à « ce rôle peut-il faire ce *type* d'action ? ».
Il ne répond pas à « cette transition est-elle légale maintenant ? » (machine à états,
statut d'un projet...) : cela reste de la logique métier, dans les services.
"""

from enum import StrEnum

from fastapi import Depends, params

from app.core.errors import AppError, ErrorCode
from app.core.security import OAUthCurrentUserDep
from app.modules.users.enums import UserRole
from app.modules.users.models import User

FORBIDDEN_MESSAGE = "Permissions insuffisantes"


class Permission(StrEnum):
    # --- Exemple : projets (module `projects`, à remplacer par vos ressources) --------
    PROJECT_CREATE = "project:create"
    PROJECT_READ_OWN = "project:read:own"
    PROJECT_READ_ALL = "project:read:all"
    PROJECT_UPDATE_OWN = "project:update:own"
    PROJECT_UPDATE_ALL = "project:update:all"
    PROJECT_DELETE_OWN = "project:delete:own"
    PROJECT_DELETE_ALL = "project:delete:all"

    # --- Supervision -----------------------------------------------------------------
    AUDIT_READ = "audit:read"


P = Permission

_USER: frozenset[Permission] = frozenset(
    {
        P.PROJECT_CREATE,
        P.PROJECT_READ_OWN,
        P.PROJECT_UPDATE_OWN,
        P.PROJECT_DELETE_OWN,
    }
)

# L'administrateur supervise et arbitre : il lit et modère tout, mais ne crée pas de projets à
# la place des utilisateurs. Tout ce qui n'est pas listé ici est accordé (`frozenset(Permission)`).
_ADMIN_EXCLUDED: frozenset[Permission] = frozenset({P.PROJECT_CREATE})

_ADMIN: frozenset[Permission] = frozenset(Permission) - _ADMIN_EXCLUDED

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.USER: _USER,
    UserRole.ADMIN: _ADMIN,
}


def permissions_of(user: User) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(user.role, frozenset())


def can(user: User, permission: Permission) -> bool:
    return permission in permissions_of(user)


def ensure(user: User, permission: Permission, detail: str = FORBIDDEN_MESSAGE) -> None:
    """Lève 403 si l'utilisateur n'a pas la permission (pour les contrôles dans un service)."""
    if not can(user, permission):
        raise AppError(403, ErrorCode.FORBIDDEN, detail)


def ensure_owner_or_permission(
    user: User,
    owner_id: object,
    all_scope: Permission,
    detail: str = "Accès refusé",
) -> None:
    """Portée « own » : le propriétaire passe, sinon il faut la permission `*_ALL`.

    Remplace le motif `if user.role != ADMIN and resource.user_id != user.id` qui était
    réécrit dans chaque service.
    """
    if owner_id != user.id and not can(user, all_scope):
        raise AppError(403, ErrorCode.FORBIDDEN, detail)


def Requires(permission: Permission) -> params.Depends:
    """Dépendance FastAPI : authentifie puis exige `permission` (401 sinon 403).

    Usage : `user: Annotated[User, Requires(Permission.ORDER_CREATE)]`.
    """

    def checker(user: OAUthCurrentUserDep) -> User:
        ensure(user, permission)
        return user

    # Lu par scripts/generate_api_reference.py pour documenter les rôles autorisés par route.
    checker.required_permissions = (permission,)  # type: ignore[attr-defined]
    return Depends(checker)


def RequiresAny(*permissions: Permission) -> params.Depends:
    """Dépendance FastAPI : exige AU MOINS UNE des permissions (ex. portée own / assigned / all).

    La portée exacte est ensuite appliquée par le service.
    """

    def checker(user: OAUthCurrentUserDep) -> User:
        if not any(can(user, permission) for permission in permissions):
            raise AppError(403, ErrorCode.FORBIDDEN, FORBIDDEN_MESSAGE)
        return user

    checker.required_permissions = permissions  # type: ignore[attr-defined]
    return Depends(checker)
