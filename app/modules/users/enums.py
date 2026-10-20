from enum import Enum


class UserStatus(Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    DELETED = "deleted"


class UserRole(Enum):
    USER = "user"
    ADMIN = "admin"
