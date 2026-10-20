"""Logique métier de l'authentification : inscription, connexion, rafraîchissement, déconnexion."""

import logging
import secrets
from datetime import timedelta

from sqlalchemy import delete, func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from app.core.clock import utc_now
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.security import (
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.modules.audit.enums import ActorType, AuditAction, AuditOutcome
from app.modules.audit.service import AuditService
from app.modules.auth.models import UserSession
from app.modules.auth.schemas import LoginPayload, UserRegisterCreate
from app.modules.users.enums import UserStatus
from app.modules.users.models import User

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS = "Email ou mot de passe erroné"
INVALID_REFRESH = "Token de rafraîchissement invalide"

# Haché à vide pour « consommer » le même temps de calcul quand l'e-mail n'existe pas :
# sans cela, la durée de la réponse révèle quels comptes existent.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def _log_login_refused(reason: str, user_id: object = None, **fields: object) -> None:
    """Connexion refusée : WARNING sans donnée personnelle (ni e-mail, ni mot de passe) — seulement la raison."""
    logger.warning(
        "Connexion refusée",
        extra={
            "event": "auth.login.failed",
            "reason": reason,
            "user_id": str(user_id) if user_id else None,
            **fields,
        },
    )


def _load_user(session: Session, user_id) -> User | None:
    return session.get(User, user_id)


class AuthService:
    """Service d'authentification : utilisateurs, sessions et jetons JWT."""

    @staticmethod
    def register(session: Session, payload: UserRegisterCreate) -> dict:
        """Inscrit un nouvel utilisateur.

        403 si l'inscription est fermée (`REGISTRATION_ENABLED=false`) ; 409 si l'e-mail est
        déjà utilisé (insensible à la casse).
        """
        if not settings.REGISTRATION_ENABLED:
            raise AppError(403, ErrorCode.REGISTRATION_CLOSED, "Les inscriptions sont fermées")

        existing_user = session.exec(
            select(User.id).where(func.lower(User.email) == payload.email)
        ).first()
        if existing_user:
            raise AppError(409, ErrorCode.EMAIL_ALREADY_USED, "Cet email est déjà utilisé")

        user = User(
            email=payload.email,
            password_hash=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
        )
        session.add(user)
        session.flush()

        AuditService.log(
            session,
            AuditAction.AUTH_REGISTER,
            actor=user,
            resource=user,
            details={"email": user.email},
        )
        try:
            session.commit()
        except IntegrityError:
            # Deux inscriptions simultanées avec le même e-mail : la contrainte d'unicité tranche.
            session.rollback()
            raise AppError(
                409, ErrorCode.EMAIL_ALREADY_USED, "Cet email est déjà utilisé"
            ) from None

        logger.info(
            "Compte créé", extra={"event": "auth.register.succeeded", "user_id": str(user.id)}
        )

        return {
            "success": True,
            "message": "Compte créé avec succès ! Veuillez vous connecter.",
            "user": _load_user(session, user.id) or user,
        }

    @staticmethod
    def authenticate(session: Session, payload: LoginPayload) -> User:
        """Vérifie email + mot de passe et renvoie l'utilisateur si tout est valide.

        - 401 identique pour « e-mail inconnu » et « mauvais mot de passe » (pas d'énumération) ;
        - après `MAX_LOGIN_ATTEMPTS` échecs, le compte est verrouillé `LOGIN_LOCK_MINUTES` (429) ;
        - 403 si le compte est bloqué (révélé seulement avec le bon mot de passe).
        """
        now = utc_now()
        user = session.exec(
            select(User).where(func.lower(User.email) == payload.email.lower())
        ).first()

        if not user:
            verify_password(payload.password, _DUMMY_HASH)
            AuditService.log_detached(
                AuditAction.AUTH_LOGIN_FAILED,
                outcome=AuditOutcome.FAILED,
                details={"reason": "unknown_email", "email": payload.email.lower()},
            )
            _log_login_refused("unknown_email")
            raise AppError(401, ErrorCode.INVALID_CREDENTIALS, INVALID_CREDENTIALS)

        if user.locked_until and user.locked_until > now:
            wait = int((user.locked_until - now).total_seconds()) + 1
            AuditService.log_detached(
                AuditAction.AUTH_LOGIN_FAILED,
                outcome=AuditOutcome.DENIED,
                resource=user,
                details={"reason": "account_locked", "retry_after_seconds": wait},
            )
            _log_login_refused("account_locked", user.id)
            raise AppError(
                429,
                ErrorCode.ACCOUNT_LOCKED,
                "Trop de tentatives échouées : compte temporairement verrouillé",
                headers={"Retry-After": str(wait)},
            )

        if not verify_password(payload.password, user.password_hash):
            user.failed_login_attempts += 1
            _log_login_refused("bad_password", user.id, failures=user.failed_login_attempts)
            AuditService.log(
                session,
                AuditAction.AUTH_LOGIN_FAILED,
                outcome=AuditOutcome.FAILED,
                resource=user,
                details={
                    "reason": "bad_password",
                    "consecutive_failures": user.failed_login_attempts,
                },
            )
            if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
                user.failed_login_attempts = 0
                logger.warning(
                    "Compte verrouillé après échecs répétés",
                    extra={
                        "event": "auth.account.locked",
                        "user_id": str(user.id),
                        "lock_minutes": settings.LOGIN_LOCK_MINUTES,
                    },
                )
                AuditService.log(
                    session,
                    AuditAction.AUTH_ACCOUNT_LOCKED,
                    actor_type=ActorType.SYSTEM,
                    resource=user,
                    details={"lock_minutes": settings.LOGIN_LOCK_MINUTES},
                )
            session.add(user)
            session.commit()
            raise AppError(401, ErrorCode.INVALID_CREDENTIALS, INVALID_CREDENTIALS)

        if user.status == UserStatus.DELETED:
            AuditService.log_detached(
                AuditAction.AUTH_LOGIN_FAILED,
                outcome=AuditOutcome.DENIED,
                resource=user,
                details={"reason": "account_deleted"},
            )
            _log_login_refused("account_deleted", user.id)
            raise AppError(401, ErrorCode.INVALID_CREDENTIALS, INVALID_CREDENTIALS)
        if user.status != UserStatus.ACTIVE:
            AuditService.log_detached(
                AuditAction.AUTH_LOGIN_FAILED,
                outcome=AuditOutcome.DENIED,
                resource=user,
                details={"reason": "account_blocked"},
            )
            _log_login_refused("account_blocked", user.id)
            raise AppError(403, ErrorCode.ACCOUNT_BLOCKED, "Utilisateur bloqué")

        if user.failed_login_attempts or user.locked_until:
            user.failed_login_attempts = 0
            user.locked_until = None
            session.add(user)
            session.commit()

        return _load_user(session, user.id) or user

    @staticmethod
    def _enforce_session_limit(session: Session, user_id) -> None:
        """Purge les sessions expirées puis ne garde que les plus récentes (limite par compte)."""
        session.exec(
            delete(UserSession).where(
                col(UserSession.user_id) == user_id, col(UserSession.expires_at) < utc_now()
            )
        )
        sessions = session.exec(
            select(UserSession)
            .where(UserSession.user_id == user_id)
            .order_by(col(UserSession.created_at).desc(), col(UserSession.id))
        ).all()
        for stale in sessions[settings.MAX_SESSIONS_PER_USER :]:
            session.delete(stale)

    @staticmethod
    def issue_session(
        session: Session,
        user: User,
        device: str | None,
        ip_address: str | None,
    ) -> dict:
        """Émet un nouvel access_token + refresh_token et persiste la session (empreinte seule)."""
        access_token = create_access_token(user.id, user.role)
        refresh_token = secrets.token_urlsafe(64)

        new_session = UserSession(
            user_id=user.id,
            refresh_token_hash=hash_token(refresh_token),
            device=(device or "")[:255] or None,
            ip_address=ip_address,
            expires_at=utc_now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )
        session.add(new_session)
        session.flush()
        AuditService.log(
            session,
            AuditAction.AUTH_LOGIN,
            actor=user,
            resource=new_session,
            details={"device": new_session.device},
        )
        AuthService._enforce_session_limit(session, user.id)
        session.commit()
        logger.info(
            "Connexion réussie", extra={"event": "auth.login.succeeded", "user_id": str(user.id)}
        )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": _load_user(session, user.id) or user,
        }

    @staticmethod
    def refresh_tokens(
        session: Session,
        refresh_token: str,
        device: str | None = None,
        ip_address: str | None = None,
    ) -> dict:
        """Régénère access et refresh tokens depuis un refresh_token valide.

        Effectue une **rotation** : l'ancien jeton est invalidé. Présenter un jeton déjà
        tourné signale un vol : la session entière est révoquée. Un compte qui n'est plus
        actif perd sa session.
        """
        token_hash = hash_token(refresh_token)
        user_session = session.exec(
            select(UserSession).where(UserSession.refresh_token_hash == token_hash)
        ).first()

        if not user_session:
            replayed = session.exec(
                select(UserSession).where(UserSession.previous_refresh_token_hash == token_hash)
            ).first()
            if replayed:
                logger.warning(
                    "Réutilisation d'un refresh token : session révoquée",
                    extra={
                        "event": "auth.token.reuse_detected",
                        "user_id": str(replayed.user_id),
                        "session_id": str(replayed.id),
                    },
                )
                AuditService.log(
                    session,
                    AuditAction.AUTH_TOKEN_REUSE_DETECTED,
                    outcome=AuditOutcome.DENIED,
                    resource=replayed,
                    details={"user_id": replayed.user_id, "action": "session révoquée"},
                )
                session.delete(replayed)
                session.commit()
            else:
                AuditService.log_detached(
                    AuditAction.AUTH_TOKEN_REFRESHED,
                    outcome=AuditOutcome.DENIED,
                    details={"reason": "unknown_token"},
                )
            raise AppError(401, ErrorCode.INVALID_TOKEN, INVALID_REFRESH)

        if user_session.expires_at < utc_now():
            session.delete(user_session)
            session.commit()
            raise AppError(401, ErrorCode.TOKEN_EXPIRED, "Token de rafraîchissement expiré")

        user = _load_user(session, user_session.user_id)
        if not user or user.status != UserStatus.ACTIVE:
            AuditService.log(
                session,
                AuditAction.AUTH_TOKEN_REFRESHED,
                outcome=AuditOutcome.DENIED,
                resource=user_session,
                details={"reason": "account_inactive", "user_id": user_session.user_id},
            )
            session.delete(user_session)
            session.commit()
            raise AppError(401, ErrorCode.INVALID_TOKEN, INVALID_REFRESH)

        new_refresh = secrets.token_urlsafe(64)
        user_session.previous_refresh_token_hash = user_session.refresh_token_hash
        user_session.refresh_token_hash = hash_token(new_refresh)
        if device:
            user_session.device = device[:255]
        if ip_address:
            user_session.ip_address = ip_address
        user_session.expires_at = utc_now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

        session.add(user_session)
        AuditService.log(
            session, AuditAction.AUTH_TOKEN_REFRESHED, actor=user, resource=user_session
        )
        session.commit()

        return {
            "access_token": create_access_token(user.id, user.role),
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "user": _load_user(session, user.id) or user,
        }

    @staticmethod
    def logout(session: Session, refresh_token: str) -> dict:
        """Clôt la session associée à un refresh_token (suppression).

        Lève 404 si aucune session ne correspond au token.
        """
        user_session = session.exec(
            select(UserSession).where(UserSession.refresh_token_hash == hash_token(refresh_token))
        ).first()
        if not user_session:
            raise AppError(404, ErrorCode.NOT_FOUND, "Session non trouvée")

        AuditService.log(
            session,
            AuditAction.AUTH_LOGOUT,
            actor=session.get(User, user_session.user_id),
            resource=user_session,
        )
        owner_id = (
            user_session.user_id
        )  # lu avant la suppression : l'objet n'est plus utilisable après
        session.delete(user_session)
        session.commit()
        logger.info("Déconnexion", extra={"event": "auth.logout", "user_id": str(owner_id)})
        return {"success": True, "message": "Déconnexion réussie"}
