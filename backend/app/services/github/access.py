"""Repository visibility and delivery boundaries shared by bot command paths."""

from contextvars import ContextVar

from sqlalchemy import exists, false, select

from app.models import GithubRepository, PushRule

notification_scope: ContextVar[tuple[int, int] | None] = ContextVar("github_notification_scope", default=None)


def command_repository_scope(account_id: int, group_number: int | None, *, is_private: bool):
    """An enabled push rule is the explicit grant to this account and group.

    A QQ sender has no implicit relationship with a console user. Private
    messages therefore get no repository grant, even for bot super-admins.
    """
    if is_private or group_number is None:
        return false()
    return (
        GithubRepository.archived_at.is_(None)
        & GithubRepository.remote_available.is_(True)
        & exists(select(PushRule.id).where(
            PushRule.repository_id == GithubRepository.id,
            PushRule.account_id == account_id,
            PushRule.qq_group == group_number,
            PushRule.enabled.is_(True),
        ))
    )


def scoped_push_query(repository_id: int):
    query = select(PushRule).where(PushRule.repository_id == repository_id, PushRule.enabled.is_(True))
    scope = notification_scope.get()
    if scope is not None:
        query = query.where(PushRule.account_id == scope[0], PushRule.qq_group == scope[1])
    return query
