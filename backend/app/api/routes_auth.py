"""
用户认证路由：注册、登录、刷新 Token、登出、获取当前用户信息。

端点列表：
  POST /api/auth/register  — 注册新用户
  POST /api/auth/login     — 用户名密码登录，返回 access + refresh token
  POST /api/auth/refresh   — 用 refresh token 换取新的 token 对（token rotation）
  POST /api/auth/logout    — 吊销当前 refresh token
  GET  /api/auth/me        — 获取当前登录用户信息（需 Bearer token）
"""
from __future__ import annotations

import logging
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_current_active_user,
    hash_password_async,
    verify_password_async,
)
from app.db.models import RefreshToken, User
from app.db.session import get_db_session
from app.schemas.auth_schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UpdateProfileRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["认证"])


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------

async def _get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# POST /api/auth/register
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="注册新用户",
)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> RegisterResponse:
    user = User(
        username=body.username,
        hashed_password=await hash_password_async(body.password),
        email=body.email or None,
        phone=body.phone or None,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        # 并发注册相同用户名时，由数据库唯一约束保证正确性
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已被注册",  # 故意不带用户名，减少信息泄露
        )

    access_token, expires_in = create_access_token(user.id)
    refresh_token_str, jti, expires_at = create_refresh_token(user.id)

    db.add(RefreshToken(user_id=user.id, jti=jti, expires_at=expires_at))
    await db.commit()
    await db.refresh(user)

    logger.info("新用户注册成功: user_id=%s ip=%s", user.id, request.client.host if request.client else "unknown")

    return RegisterResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token_str,
        expires_in=expires_in,
    )


# ---------------------------------------------------------------------------
# POST /api/auth/login
# ---------------------------------------------------------------------------

@router.post(
    "/login",
    response_model=LoginResponse,
    summary="用户登录",
)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    client_ip = request.client.host if request.client else "unknown"
    user = await _get_user_by_username(db, body.username)

    if user is None or not await verify_password_async(body.password, user.hashed_password):
        logger.warning("登录失败: username=%s ip=%s", body.username, client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        logger.warning("禁用账户尝试登录: user_id=%s ip=%s", user.id, client_ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用，请联系管理员",
        )

    access_token, expires_in = create_access_token(user.id)
    refresh_token_str, jti, expires_at = create_refresh_token(user.id)

    db.add(RefreshToken(user_id=user.id, jti=jti, expires_at=expires_at))
    await db.commit()

    logger.info("用户登录成功: user_id=%s ip=%s", user.id, client_ip)

    return LoginResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token_str,
        expires_in=expires_in,
    )


# ---------------------------------------------------------------------------
# POST /api/auth/refresh  — Token 自动续期（rotation 模式）
# ---------------------------------------------------------------------------

@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="刷新 Token（自动续期）",
    description=(
        "提交有效的 refresh token，返回新的 access token + 新的 refresh token。"
        "旧 refresh token 立即吊销（token rotation），防止重放攻击。"
    ),
)
async def refresh_token(
    body: RefreshRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    client_ip = request.client.host if request.client else "unknown"
    user_id, jti = decode_refresh_token(body.refresh_token)

    result = await db.execute(
        select(RefreshToken).where(RefreshToken.jti == jti)
    )
    token_record: RefreshToken | None = result.scalar_one_or_none()

    # 统一错误信息，不暴露 token 是否存在
    _invalid_err = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Refresh token 无效，请重新登录",
    )

    if token_record is None:
        raise _invalid_err

    if token_record.revoked:
        # 检测到已吊销 token 被重用 — 可能发生了 token 盗用，吊销该用户所有 token
        logger.critical(
            "⚠️ 检测到 refresh token 重用攻击: user_id=%s jti=%s ip=%s",
            user_id, jti, client_ip,
        )
        revoke_result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked == False,  # noqa: E712
            )
        )
        for rt in revoke_result.scalars().all():
            rt.revoked = True
        await db.commit()
        raise _invalid_err

    # JWT 的 exp 已由 decode_refresh_token 校验，此处无需重复检查 expires_at

    # 吊销旧 token（rotation）
    token_record.revoked = True

    # 确认用户仍然有效
    user_result = await db.execute(select(User).where(User.id == user_id))
    user: User | None = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        await db.commit()   # 提交 revoked=True，防止此 token 被再次使用
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
        )

    # 颁发新的 token 对
    new_access_token, expires_in = create_access_token(user_id)
    new_refresh_token_str, new_jti, new_expires_at = create_refresh_token(user_id)

    db.add(RefreshToken(user_id=user_id, jti=new_jti, expires_at=new_expires_at))
    await db.commit()

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token_str,
        expires_in=expires_in,
        user=UserResponse.model_validate(user),
    )


# ---------------------------------------------------------------------------
# POST /api/auth/logout
# ---------------------------------------------------------------------------

@router.post(
    "/logout",
    summary="登出（吊销 refresh token）",
)
async def logout(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    try:
        _, jti = decode_refresh_token(body.refresh_token)
    except HTTPException:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    result = await db.execute(
        select(RefreshToken).where(RefreshToken.jti == jti)
    )
    token_record = result.scalar_one_or_none()
    if token_record and not token_record.revoked:
        token_record.revoked = True
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# GET /api/auth/me
# ---------------------------------------------------------------------------

@router.get(
    "/me",
    response_model=UserResponse,
    summary="获取当前登录用户信息",
)
async def get_me(
    current_user: User = Depends(get_current_active_user),
) -> UserResponse:
    return UserResponse.model_validate(current_user)


# ---------------------------------------------------------------------------
# POST /api/auth/change-password
# ---------------------------------------------------------------------------

@router.post(
    "/change-password",
    summary="修改密码",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """
    修改当前用户密码。需提供旧密码校验，成功后写入新密码哈希。
    """
    if not await verify_password_async(body.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="旧密码不正确",
        )
    if body.old_password == body.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码不能与旧密码相同",
        )
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    user.hashed_password = await hash_password_async(body.new_password)
    await db.commit()
    logger.info("用户密码已修改: user_id=%s", current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# PATCH /api/auth/me  — 更新个人资料（邮箱/手机/角色）
# ---------------------------------------------------------------------------

@router.patch(
    "/me",
    response_model=UserResponse,
    summary="更新当前用户资料",
)
async def update_me(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db_session),
) -> UserResponse:
    """
    更新当前用户的邮箱、手机号。管理员账号可自助调整 role（MVP 阶段对所有登录用户开放）。
    """
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    if body.username is not None and body.username.strip():
        user.username = body.username.strip()
    if body.email is not None:
        user.email = body.email or None
    if body.phone is not None:
        user.phone = body.phone or None

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名或邮箱已被其他账号使用",
        )
    await db.refresh(user)
    logger.info("用户资料已更新: user_id=%s", current_user.id)
    return UserResponse.model_validate(user)
