from enum import StrEnum


class AuditOutcome(StrEnum):
    SUCCESS = "success"  # l'opération a eu lieu
    DENIED = "denied"  # refusée (droits, signature, verrou…)
    FAILED = "failed"  # tentée mais échouée (mauvais mot de passe…)


class ActorType(StrEnum):
    USER = "user"  # un utilisateur authentifié
    SYSTEM = "system"  # le système lui-même (tâche planifiée, webhook d'un prestataire…)
    ANONYMOUS = "anonymous"  # personne d'authentifié (connexion ratée…)


class AuditAction(StrEnum):
    """Catalogue fermé des actions journalisées : une faute de frappe est impossible, et un test
    vérifie que chaque action est réellement émise quelque part dans le code."""

    # --- Authentification & sessions
    AUTH_REGISTER = "auth.register"
    AUTH_LOGIN = "auth.login"
    AUTH_LOGIN_FAILED = "auth.login_failed"
    AUTH_ACCOUNT_LOCKED = "auth.account_locked"
    AUTH_LOGOUT = "auth.logout"
    AUTH_TOKEN_REFRESHED = "auth.token_refreshed"  # noqa: S105 — nom d'action, pas un secret
    AUTH_TOKEN_REUSE_DETECTED = "auth.token_reuse_detected"  # noqa: S105 — nom d'action, pas un secret
    # --- Accès
    ACCESS_DENIED = "access.denied"
    # --- Comptes
    USER_ADMIN_CREATED = "user.admin_created"  # par le script scripts/create_admin.py
    # --- Exemple : projets (à remplacer par vos ressources)
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_STATUS_CHANGED = "project.status_changed"
    PROJECT_DELETED = "project.deleted"
    # --- Données sensibles consultées
    AUDIT_VIEWED = "audit.viewed"
