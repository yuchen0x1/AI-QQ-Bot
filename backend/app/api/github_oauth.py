"""GitHub OAuth 授权：绑定/解绑、仓库列表与批量导入、OAuth App 配置。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, require
from app.core.security import decrypt_secret
from app.db.session import get_db
from app.models import GithubRepository, User
from app.schemas.common import MessageOut
from app.schemas.github import (
    GithubAccountOut,
    GithubImportIn,
    GithubImportResult,
    GithubOAuthAppIn,
    GithubOAuthAppOut,
    GithubOAuthStatus,
    GithubRepoItem,
    GithubRepoList,
)
from app.services.github.client import GithubError
from app.services.github.oauth import (
    MAX_REPOS_PER_PAGE,
    OAuthError,
    append_query,
    authorize_url,
    build_state,
    delete_token,
    exchange_code,
    fetch_github_user,
    get_oauth_app,
    get_user_token,
    list_user_repos,
    parse_state,
    profile_summary,
    redirect_uri,
    sanitize_next,
    save_oauth_app,
    save_token,
)
from app.services.github.registry import RepositoryExistsError, create_monitored_repo
from app.services.logs import audit, write_log

logger = logging.getLogger("qbot.github.oauth.api")
router = APIRouter(prefix="/github/oauth", tags=["GitHub OAuth"])

SETUP_STEPS = [
    "打开 GitHub → Settings → Developer settings → OAuth Apps → New OAuth App",
    "Homepage URL 填本站地址；Authorization callback URL 必须填下方「回调地址」，否则 GitHub 会拒绝授权",
    "创建后复制 Client ID，点击 Generate a new client secret 生成密钥",
    "把 Client ID / Client Secret 填入本页并保存（密钥加密存储在数据库，不会回显）",
    "保存后在 GitHub 页面点击「绑定 GitHub 账号」，授权完成即可一键导入仓库",
]


def _app_out(app) -> GithubOAuthAppOut:
    return GithubOAuthAppOut(
        configured=app is not None,
        client_id=app.masked_client_id if app else None,
        has_secret=app is not None,
        scopes=app.scopes if app else None,
        source=app.source if app else None,
        redirect_uri=redirect_uri(),
        steps=SETUP_STEPS,
    )


@router.get("/status", response_model=GithubOAuthStatus)
async def oauth_status(db: AsyncSession = Depends(get_db), user: User = Depends(require("github:view"))):
    app = await get_oauth_app(db)
    row = await get_user_token(db, user.id)
    summary = profile_summary(row)
    return GithubOAuthStatus(
        configured=app is not None,
        connected=row is not None,
        source=app.source if app else None,
        scopes=app.scopes if app else None,
        redirect_uri=redirect_uri(),
        account=GithubAccountOut(**summary) if summary else None,
        can_configure=bool({"*", "system:manage"} & user.permission_set),
        message=None if app else "尚未配置 GitHub OAuth App，配置后才能绑定账号并导入仓库",
    )


@router.get("/start")
async def oauth_start(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("github:manage")),
):
    """浏览器整页跳转入口：带着登录 Cookie 发起授权，返回 302 到 GitHub。"""
    app = await get_oauth_app(db)
    if not app:
        raise HTTPException(status_code=400, detail="尚未配置 GitHub OAuth App，请先填写 Client ID 与 Client Secret")
    state = build_state(user, request.query_params.get("next"))
    response = RedirectResponse(authorize_url(app, state), status_code=302)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/callback")
async def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """GitHub 回调：校验签名 state → 用 code 换 Token → 绑定到发起授权的平台用户。"""

    def fail(reason: str) -> RedirectResponse:
        return RedirectResponse(append_query("/github", github="error", reason=reason[:180]), status_code=302)

    if error:
        return fail(error_description or error)
    payload = parse_state(state)
    if not payload:
        return fail("授权状态已失效或签名不匹配，请重新发起绑定")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return fail("授权状态无效，请重新发起绑定")
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        return fail("当前平台账号不可用，请重新登录后再试")
    app = await get_oauth_app(db)
    if not app:
        return fail("尚未配置 GitHub OAuth App")
    if not code:
        return fail("GitHub 未返回授权码")

    try:
        token_payload = await exchange_code(app, code)
        profile = await fetch_github_user(token_payload["access_token"])
        row = await save_token(db, user, token_payload, profile)
    except OAuthError as exc:
        await write_log(db, level="WARNING", category="github", message=f"GitHub 授权失败：{exc}")
        return fail(str(exc))
    except Exception:  # noqa: BLE001
        logger.exception("GitHub OAuth 回调异常")
        await write_log(db, level="ERROR", category="github", message="GitHub 授权回调处理异常，请查看后端日志")
        return fail("授权处理失败，请稍后重试或联系管理员")

    await audit(db, user_id=user.id, username=user.username, action="bind_github", target=row.login, ip=client_ip(request))
    await write_log(db, level="INFO", category="github", message=f"用户 {user.username} 绑定 GitHub 账号 {row.login}")
    return RedirectResponse(
        append_query(sanitize_next(payload.get("next")), github="connected", login=row.login), status_code=302
    )


@router.post("/disconnect", response_model=MessageOut)
async def oauth_disconnect(
    request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require("github:manage"))
):
    row = await get_user_token(db, user.id)
    if not row:
        raise HTTPException(status_code=404, detail="尚未绑定 GitHub 账号")
    login = row.login
    await delete_token(db, user.id)
    await audit(db, user_id=user.id, username=user.username, action="unbind_github", target=login, ip=client_ip(request))
    await write_log(db, level="INFO", category="github", message=f"用户 {user.username} 解绑 GitHub 账号 {login}")
    return MessageOut(detail=f"已解除与 GitHub 账号 {login} 的绑定，已监控仓库不受影响（会改用其它可用凭据）")


@router.get("/repos", response_model=GithubRepoList)
async def my_repos(
    page: int = Query(default=1, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require("github:manage")),
):
    row = await get_user_token(db, user.id)
    if not row:
        raise HTTPException(status_code=400, detail="请先绑定 GitHub 账号")
    token = decrypt_secret(row.access_token_enc)
    if not token:
        raise HTTPException(status_code=400, detail="GitHub 授权已失效，请重新绑定")
    try:
        items = await list_user_repos(token, page=page, per_page=MAX_REPOS_PER_PAGE)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    names = [item["full_name"].lower() for item in items]
    monitored: dict[str, int] = {}
    if names:
        rows = await db.execute(
            select(GithubRepository.id, GithubRepository.full_name).where(
                func.lower(GithubRepository.full_name).in_(names)
            )
        )
        monitored = {full_name.lower(): repo_id for repo_id, full_name in rows.all()}
    result = [
        GithubRepoItem(**item, monitored=item["full_name"].lower() in monitored, repo_id=monitored.get(item["full_name"].lower()))
        for item in items
    ]
    return GithubRepoList(items=result, page=page, per_page=MAX_REPOS_PER_PAGE, has_more=len(items) >= MAX_REPOS_PER_PAGE)


@router.post("/import", response_model=GithubImportResult)
async def import_repos(
    payload: GithubImportIn, db: AsyncSession = Depends(get_db), user: User = Depends(require("github:manage"))
):
    row = await get_user_token(db, user.id)
    if not row:
        raise HTTPException(status_code=400, detail="请先绑定 GitHub 账号")
    token = decrypt_secret(row.access_token_enc)
    if not token:
        raise HTTPException(status_code=400, detail="GitHub 授权已失效，请重新绑定")

    result = GithubImportResult()
    for raw in payload.full_names:
        full_name = (raw or "").strip()
        if "/" not in full_name:
            result.failed.append({"full_name": full_name, "error": "仓库名格式应为 owner/repo"})
            continue
        owner, name = full_name.split("/", 1)
        try:
            repo, _ = await create_monitored_repo(
                db,
                provider="github",
                owner=owner.strip(),
                name=name.strip(),
                token=token,
                poll_interval_seconds=payload.poll_interval_seconds,
                notify_prerelease=payload.notify_prerelease,
                owner_user_id=user.id,
                persist_token=False,
            )
        except RepositoryExistsError:
            result.skipped.append(full_name)
        except GithubError as exc:
            result.failed.append({"full_name": full_name, "error": str(exc)[:200]})
        except Exception as exc:  # noqa: BLE001
            logger.warning("导入仓库 %s 失败: %s", full_name, exc)
            result.failed.append({"full_name": full_name, "error": str(exc)[:200]})
        else:
            result.imported.append(repo.full_name)

    if result.imported:
        await audit(
            db,
            user_id=user.id,
            username=user.username,
            action="import_repos",
            target=f"{len(result.imported)} 个仓库",
            detail=", ".join(result.imported)[:500],
        )
        await write_log(
            db,
            level="INFO",
            category="github",
            message=f"{user.username} 通过 GitHub 授权导入 {len(result.imported)} 个仓库（历史版本不推送）",
            context={"repos": result.imported[:20]},
        )
    return result


@router.get("/app", response_model=GithubOAuthAppOut)
async def read_app(db: AsyncSession = Depends(get_db), _: User = Depends(require("system:manage"))):
    return _app_out(await get_oauth_app(db))


@router.put("/app", response_model=GithubOAuthAppOut)
async def update_app(
    payload: GithubOAuthAppIn, db: AsyncSession = Depends(get_db), user: User = Depends(require("system:manage"))
):
    try:
        app = await save_oauth_app(db, client_id=payload.client_id, client_secret=payload.client_secret, scopes=payload.scopes)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await audit(db, user_id=user.id, username=user.username, action="update_github_oauth_app", target="github_oauth")
    await write_log(db, level="INFO", category="github", message="GitHub OAuth App 凭据已更新")
    return _app_out(app)
