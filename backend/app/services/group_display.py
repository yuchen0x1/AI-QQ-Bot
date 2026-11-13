"""Human-provided QQ group numbers are display labels; OpenID mappings remain routing keys."""

from sqlalchemy import select
from app.models import Account, Group


def display_number(group: Group, protocol: str | None = None) -> str | None:
    if group.display_number:
        return group.display_number
    return None


def display_name(group: Group, protocol: str | None = None) -> str:
    number = display_number(group, protocol)
    if group.name and group.name not in {f"群 {group.group_number}", f"群{group.group_number}", f"官方群 {group.group_number}"}:
        return group.name
    return f"QQ群 {number}" if number else "未标注群号"


async def group_labels(db) -> dict[tuple[int, int], dict]:
    rows = await db.execute(select(Group, Account.protocol).join(Account, Account.id == Group.account_id))
    return {(g.account_id, g.group_number): {"number": display_number(g, protocol), "name": display_name(g, protocol)} for g, protocol in rows}
