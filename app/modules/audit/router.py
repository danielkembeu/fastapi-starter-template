from typing import Annotated

from fastapi import APIRouter, Query

from app.core.authz import Permission, Requires
from app.core.database import DBSessionDep
from app.core.errors import err
from app.core.pagination import Page
from app.modules.audit.enums import AuditAction
from app.modules.audit.schemas import AuditFilters, AuditLogRead
from app.modules.audit.service import AuditService
from app.modules.users.models import User

router = APIRouter(prefix="/admin/audit-logs", tags=["Audit"], responses=err(400, 500))

AuditReaderDep = Annotated[User, Requires(Permission.AUDIT_READ)]


@router.get("", response_model=Page[AuditLogRead], responses=err(401, 403))
def list_audit_logs(
    session: DBSessionDep,
    admin: AuditReaderDep,
    filters: Annotated[AuditFilters, Query()],
):
    """Journal d'audit : toutes les opérations, les plus récentes d'abord (administrateurs uniquement).

    Le journal est en **ajout seul** : aucune route ne permet de modifier ou supprimer une entrée.
    Filtres utiles : `resource_type` + `resource_id` (historique complet d'une ressource),
    `actor_id` (tout ce qu'un utilisateur a fait), `action`, `outcome` (`denied`/`failed` pour les
    incidents), `request_id` (tout ce qu'une requête a déclenché). Consulter le journal est lui-même journalisé.
    """
    result = AuditService.list_logs(session, filters.page, filters)
    AuditService.log(
        session,
        AuditAction.AUDIT_VIEWED,
        actor=admin,
        details=filters.model_dump(exclude={"limit", "offset", "sort"}, exclude_none=True),
    )
    session.commit()
    return result
