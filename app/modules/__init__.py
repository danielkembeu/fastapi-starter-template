# Registre des modèles : ces imports peuplent `SQLModel.metadata` pour Alembic et les tests.
# Ils paraissent inutilisés mais ne doivent PAS être supprimés (voir pyproject : F401 ignoré ici).
# Ajouter ici le modèle de chaque nouveau module.
from .audit.models import AuditLog
from .auth.models import UserSession
from .projects.models import Project
from .users.models import User
