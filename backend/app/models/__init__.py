"""统一导出所有 ORM 模型，保证 Alembic / metadata 能发现全部表。"""

from app.models.account import (
    Account,
    AccountConnection,
    Group,
    GroupMember,
    GroupSettings,
    Message,
    QQOfficialIdentity,
)
from app.models.ai import (
    AIConversation,
    AIMessage,
    AIModel,
    AIProvider,
    AIUsageLog,
)
from app.models.base import Base, utcnow
from app.models.request import BotRequest
from app.models.github import (
    GithubEvent,
    GithubNotificationTarget,
    GithubRelease,
    GithubRepository,
    PushRecord,
    PushRule,
    UserGithubToken,
)
from app.models.task import (
    BotCommand,
    LoginAttempt,
    Plugin,
    PluginBinding,
    ScheduledTask,
    SystemLog,
    SystemSetting,
    TaskRecord,
)
from app.models.user import AuditLog, AuthSession, Role, User
from app.models.email_alert import EmailAlert

__all__ = [
    "Base",
    "EmailAlert",
    "utcnow",
    "User",
    "Role",
    "AuditLog",
    "AuthSession",
    "Account",
    "AccountConnection",
    "Group",
    "GroupSettings",
    "GroupMember",
    "Message",
    "QQOfficialIdentity",
    "AIProvider",
    "AIModel",
    "AIConversation",
    "AIMessage",
    "AIUsageLog",
    "GithubRepository",
    "GithubRelease",
    "GithubEvent",
    "GithubNotificationTarget",
    "PushRule",
    "PushRecord",
    "UserGithubToken",
    "ScheduledTask",
    "TaskRecord",
    "Plugin",
    "PluginBinding",
    "BotCommand",
    "SystemLog",
    "SystemSetting",
    "LoginAttempt",
    "BotRequest",
]
