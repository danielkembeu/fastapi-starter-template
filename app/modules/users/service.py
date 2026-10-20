"""Logique métier des comptes utilisateurs (hors authentification)."""

from sqlalchemy import func
from sqlmodel import Session, select

from app.core.errors import AppError, ErrorCode
from app.core.security import hash_password
from app.core.validators import check_password
from app.modules.audit.enums import ActorType, AuditAction
from app.modules.audit.service import AuditService
from app.modules.users.enums import UserRole
from app.modules.users.models import User


class UserService:
    @staticmethod
    def create_admin(
        session: Session, *, email: str, password: str, first_name: str, last_name: str
    ) -> User:
        """Crée un compte administrateur. Utilisé par `scripts/create_admin.py` : aucune route ne le fait.

        Aucune route publique ne peut créer un administrateur ; c'est ce qui garantit qu'un rôle
        privilégié ne s'obtient jamais par l'API. Le mot de passe suit la même politique que l'inscription.
        """
        email = email.strip().lower()
        try:
            check_password(password)
        except ValueError as exc:
            raise AppError(400, ErrorCode.WEAK_PASSWORD, str(exc)) from None
        if session.exec(select(User.id).where(func.lower(User.email) == email)).first():
            raise AppError(409, ErrorCode.EMAIL_ALREADY_USED, "Cet email est déjà utilisé")

        admin = User(
            email=email,
            password_hash=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            role=UserRole.ADMIN,
        )
        session.add(admin)
        session.flush()
        AuditService.log(
            session,
            AuditAction.USER_ADMIN_CREATED,
            actor_type=ActorType.SYSTEM,
            resource=admin,
            details={"email": email, "via": "scripts/create_admin"},
        )
        session.commit()
        session.refresh(admin)
        return admin
