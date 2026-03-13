"""
认证模块测试套件
================
测试层级：
  Layer 1 — 单元测试（纯函数，无 HTTP / DB）：
              密码哈希、JWT 生成/解码、Schema 输入校验
  Layer 2 — API 测试（mock DB，走完整 FastAPI 路由）：
              register / login / refresh / logout / me 全路径

运行方式：
  pytest tests/test_auth.py -v
  pytest tests/test_auth.py -v -k "TestSecurity"     # 只跑单元测试
  pytest tests/test_auth.py -v -k "TestRegister"     # 只跑注册
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db_session
from app.schemas.auth_schemas import LoginRequest, RefreshRequest, RegisterRequest
from main import app


# ===========================================================================
# 测试工具 & 共享 Fixture
# ===========================================================================

_VALID_USERNAME = "testuser"
_VALID_PASSWORD = "Test1234"


def _make_user(
    user_id: str | None = None,
    username: str = _VALID_USERNAME,
    password: str = _VALID_PASSWORD,
    is_active: bool = True,
) -> MagicMock:
    """
    构造一个模拟 User ORM 对象。
    user.hashed_password 使用真实 bcrypt 哈希，使 verify_password 可以正常工作。
    """
    user = MagicMock()
    user.id = user_id or str(uuid.uuid4())
    user.username = username
    user.hashed_password = hash_password(password)
    user.is_active = is_active
    user.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return user


def _make_rt_record(
    user_id: str = "user-123",
    jti: str | None = None,
    revoked: bool = False,
    expires_at: datetime | None = None,
) -> MagicMock:
    """构造一个模拟 RefreshToken ORM 对象。"""
    rt = MagicMock()
    rt.jti = jti or str(uuid.uuid4())
    rt.user_id = user_id
    rt.revoked = revoked
    rt.expires_at = expires_at or (datetime.now(timezone.utc) + timedelta(days=7))
    return rt


def _make_db(execute_responses: list) -> AsyncMock:
    """
    构造能按顺序返回不同结果的 mock AsyncSession。

    execute_responses 是每次 db.execute() 调用按顺序返回的值列表：
      - MagicMock → scalar_one_or_none() 返回该值
      - list      → scalars().all() 返回该列表（用于 revoke all tokens 场景）
      - Exception → 模拟 execute 本身抛出异常（IntegrityError 等）
    """
    session = AsyncMock()
    responses = iter(execute_responses)

    async def _execute(query, *args, **kwargs):
        try:
            resp = next(responses)
        except StopIteration:
            resp = None

        result = MagicMock()
        if isinstance(resp, list):
            result.scalar_one_or_none.return_value = None
            result.scalars.return_value.all.return_value = resp
        else:
            result.scalar_one_or_none.return_value = resp
            result.scalars.return_value.all.return_value = [resp] if resp else []
        return result

    session.execute = _execute
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()

    async def _refresh(obj):
        """
        模拟真实 DB refresh：
        SQLAlchemy Column(default=...) 在 flush() 时由 INSERT 语句写入，
        mock 的 flush 是空操作，所以需要在 refresh 里手动补齐这些字段，
        模拟数据库回填了 id / is_active / created_at 后的状态。
        """
        if not getattr(obj, "id", None):
            obj.id = str(uuid.uuid4())
        if getattr(obj, "is_active", None) is None:
            obj.is_active = True
        if not getattr(obj, "created_at", None):
            obj.created_at = datetime.now(timezone.utc)

    session.refresh = AsyncMock(side_effect=_refresh)
    return session


@contextmanager
def _override_db(db: AsyncMock):
    """临时替换 FastAPI 的 get_db_session 依赖，测试结束自动清理。"""
    async def _dep():
        yield db

    app.dependency_overrides[get_db_session] = _dep
    try:
        yield
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ===========================================================================
# Layer 1 — 单元测试：密码哈希
# ===========================================================================

class TestPasswordHashing:
    """测试 passlib bcrypt 哈希和验证逻辑。"""

    def test_hash_is_not_plaintext(self):
        """哈希结果不应包含原始密码。"""
        h = hash_password("secret123")
        assert "secret123" not in h

    def test_hash_format_is_bcrypt(self):
        """bcrypt 哈希以 $2b$ 开头。"""
        h = hash_password("secret123")
        assert h.startswith("$2b$")

    def test_same_input_produces_different_hashes(self):
        """相同密码每次哈希结果不同（bcrypt 自动加 salt）。"""
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert h1 != h2

    def test_verify_correct_password(self):
        h = hash_password("mypassword")
        assert verify_password("mypassword", h) is True

    def test_reject_wrong_password(self):
        h = hash_password("mypassword")
        assert verify_password("wrongpassword", h) is False

    def test_reject_empty_password(self):
        h = hash_password("mypassword")
        assert verify_password("", h) is False

    def test_case_sensitive(self):
        """密码校验区分大小写。"""
        h = hash_password("Password")
        assert verify_password("password", h) is False
        assert verify_password("Password", h) is True


# ===========================================================================
# Layer 1 — 单元测试：JWT 工具函数
# ===========================================================================

class TestCreateAccessToken:
    """测试 access token 的生成格式与 claims。"""

    def test_returns_string_and_expire_seconds(self):
        token, expires_in = create_access_token("user-abc")
        assert isinstance(token, str)
        assert expires_in == 180 * 60  # 3h = 10800s

    def test_token_has_correct_claims(self):
        settings = get_settings()
        token, _ = create_access_token("user-xyz")
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        assert payload["sub"] == "user-xyz"
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload

    def test_token_expires_in_3_hours(self):
        """exp 约等于当前时间 + 3 小时（允许 ±5 秒误差）。"""
        settings = get_settings()
        token, _ = create_access_token("u")
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        expected_exp = datetime.now(timezone.utc) + timedelta(hours=3)
        actual_exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        diff = abs((actual_exp - expected_exp).total_seconds())
        assert diff < 5

    def test_different_users_produce_different_tokens(self):
        t1, _ = create_access_token("user-1")
        t2, _ = create_access_token("user-2")
        assert t1 != t2


class TestCreateRefreshToken:
    """测试 refresh token 的生成格式、jti 唯一性与 claims。"""

    def test_returns_token_jti_and_expiry(self):
        token, jti, expires_at = create_refresh_token("user-abc")
        assert isinstance(token, str)
        assert isinstance(jti, str) and len(jti) == 36  # UUID 格式
        assert isinstance(expires_at, datetime)

    def test_jti_is_unique_each_call(self):
        """每次调用生成不同的 jti（UUID v4）。"""
        _, jti1, _ = create_refresh_token("u")
        _, jti2, _ = create_refresh_token("u")
        assert jti1 != jti2

    def test_token_has_correct_claims(self):
        settings = get_settings()
        token, jti, _ = create_refresh_token("user-xyz")
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        assert payload["sub"] == "user-xyz"
        assert payload["type"] == "refresh"
        assert payload["jti"] == jti

    def test_expires_in_7_days(self):
        settings = get_settings()
        token, _, _ = create_refresh_token("u")
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        expected_exp = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )
        actual_exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        diff = abs((actual_exp - expected_exp).total_seconds())
        assert diff < 5


class TestDecodeAccessToken:
    """测试 access token 解码：正常、过期、篡改、类型错误。"""

    def test_decode_valid_token(self):
        token, _ = create_access_token("user-123")
        user_id = decode_access_token(token)
        assert user_id == "user-123"

    def test_expired_token_raises_401(self):
        """过期 token 应返回 401，不是 500。"""
        settings = get_settings()
        payload = {
            "sub": "user-123",
            "type": "access",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),  # 已过期
            "iat": datetime.now(timezone.utc) - timedelta(hours=4),
        }
        expired_token = jwt.encode(
            payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(expired_token)
        assert exc_info.value.status_code == 401

    def test_tampered_signature_raises_401(self):
        """篡改签名后，验证应失败。"""
        token, _ = create_access_token("user-123")
        # 最后几位是签名，替换它
        tampered = token[:-10] + "XXXXXXXXXXX"
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(tampered)
        assert exc_info.value.status_code == 401

    def test_refresh_token_rejected_as_access_token(self):
        """用 refresh token 当 access token 应被拒绝。"""
        rt, _, _ = create_refresh_token("user-123")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(rt)
        assert exc_info.value.status_code == 401

    def test_wrong_secret_raises_401(self):
        payload = {
            "sub": "user-123",
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=3),
        }
        fake_token = jwt.encode(payload, "wrong-secret", algorithm="HS256")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(fake_token)
        assert exc_info.value.status_code == 401


class TestDecodeRefreshToken:
    """测试 refresh token 解码的正常与异常路径。"""

    def test_decode_valid_refresh_token(self):
        token, jti, _ = create_refresh_token("user-456")
        user_id, decoded_jti = decode_refresh_token(token)
        assert user_id == "user-456"
        assert decoded_jti == jti

    def test_access_token_rejected_as_refresh_token(self):
        """用 access token 当 refresh token 应被拒绝。"""
        at, _ = create_access_token("user-123")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            decode_refresh_token(at)
        assert exc_info.value.status_code == 401


# ===========================================================================
# Layer 1 — 单元测试：Schema 输入校验
# ===========================================================================

class TestRegisterRequestSchema:
    """验证注册请求的 Pydantic 校验规则。"""

    def test_valid_input(self):
        req = RegisterRequest(username="alice", password="Alice123")
        assert req.username == "alice"

    def test_username_converted_to_lowercase(self):
        req = RegisterRequest(username="ALICE", password="Alice123")
        assert req.username == "alice"

    def test_username_too_short(self):
        with pytest.raises(ValidationError):
            RegisterRequest(username="ab", password="Alice123")

    def test_username_too_long(self):
        with pytest.raises(ValidationError):
            RegisterRequest(username="a" * 51, password="Alice123")

    def test_username_invalid_characters(self):
        """用户名只允许 \\w（字母数字下划线），不允许空格/连字符。"""
        with pytest.raises(ValidationError):
            RegisterRequest(username="alice bob", password="Alice123")
        with pytest.raises(ValidationError):
            RegisterRequest(username="alice-bob", password="Alice123")

    def test_password_too_short(self):
        with pytest.raises(ValidationError):
            RegisterRequest(username="alice", password="Ab1")

    def test_password_no_digit_rejected(self):
        """密码没有数字应被拒绝。"""
        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(username="alice", password="abcdefgh")
        assert "数字" in str(exc_info.value)

    def test_password_no_letter_rejected(self):
        """密码没有字母应被拒绝。"""
        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(username="alice", password="12345678")
        assert "字母" in str(exc_info.value)

    def test_password_max_length(self):
        with pytest.raises(ValidationError):
            RegisterRequest(username="alice", password="A1" + "x" * 200)


class TestRefreshRequestSchema:
    """验证 refresh token 的长度限制（DoS 防护）。"""

    def test_valid_token(self):
        req = RefreshRequest(refresh_token="valid.jwt.token")
        assert req.refresh_token == "valid.jwt.token"

    def test_empty_token_rejected(self):
        with pytest.raises(ValidationError):
            RefreshRequest(refresh_token="")

    def test_oversized_token_rejected(self):
        """超过 2048 字符的 token 应被 Pydantic 拒绝，不进入业务逻辑。"""
        with pytest.raises(ValidationError):
            RefreshRequest(refresh_token="x" * 2049)


# ===========================================================================
# Layer 2 — API 测试：POST /api/auth/register
# ===========================================================================

class TestRegisterEndpoint:
    """完整的 HTTP 注册路径测试。"""

    @pytest.mark.asyncio
    async def test_register_success(self, client):
        """注册成功返回 201 + access_token + refresh_token + user 信息。"""
        db = _make_db([])  # flush 不抛异常
        with _override_db(db):
            resp = await client.post(
                "/api/auth/register",
                json={"username": "newuser", "password": "NewUser1"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 10800
        assert data["user"]["username"] == "newuser"
        assert "id" in data["user"]
        assert "hashed_password" not in data   # 密码哈希绝不出现在响应里

    @pytest.mark.asyncio
    async def test_register_duplicate_username_returns_409(self, client):
        """重复用户名由数据库唯一约束捕获，返回 409。"""
        db = _make_db([])
        # flush 时模拟数据库唯一约束违反
        db.flush = AsyncMock(side_effect=IntegrityError("", {}, Exception()))
        with _override_db(db):
            resp = await client.post(
                "/api/auth/register",
                json={"username": "existinguser", "password": "Exist123"},
            )
        assert resp.status_code == 409
        assert "已被注册" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_register_username_too_short_returns_422(self, client):
        """用户名不足 3 字符，Pydantic 直接返回 422，不触碰 DB。"""
        resp = await client.post(
            "/api/auth/register",
            json={"username": "ab", "password": "Valid123"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_register_weak_password_returns_422(self, client):
        """纯数字密码不符合复杂度要求，返回 422。"""
        resp = await client.post(
            "/api/auth/register",
            json={"username": "alice", "password": "12345678"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_register_username_stored_as_lowercase(self, client):
        """用户名大写输入，存储时统一转为小写。"""
        db = _make_db([])
        with _override_db(db):
            resp = await client.post(
                "/api/auth/register",
                json={"username": "UPPERCASE", "password": "Upper123"},
            )
        assert resp.status_code == 201
        assert resp.json()["user"]["username"] == "uppercase"

    @pytest.mark.asyncio
    async def test_register_response_contains_no_sensitive_fields(self, client):
        """响应中不能出现 hashed_password 等敏感字段。"""
        db = _make_db([])
        with _override_db(db):
            resp = await client.post(
                "/api/auth/register",
                json={"username": "safeuser", "password": "Safe1234"},
            )
        assert resp.status_code == 201
        resp_text = resp.text
        assert "hashed_password" not in resp_text
        assert "password" not in resp_text


# ===========================================================================
# Layer 2 — API 测试：POST /api/auth/login
# ===========================================================================

class TestLoginEndpoint:

    @pytest.mark.asyncio
    async def test_login_success(self, client):
        """正确的用户名密码返回 200 + token 对。"""
        user = _make_user()
        db = _make_db([user])  # 第一次 execute 返回 user
        with _override_db(db):
            resp = await client.post(
                "/api/auth/login",
                json={"username": _VALID_USERNAME, "password": _VALID_PASSWORD},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password_returns_401(self, client):
        user = _make_user()  # 密码是 _VALID_PASSWORD
        db = _make_db([user])
        with _override_db(db):
            resp = await client.post(
                "/api/auth/login",
                json={"username": _VALID_USERNAME, "password": "WrongPass1"},
            )
        assert resp.status_code == 401
        assert "用户名或密码错误" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_nonexistent_user_same_error_as_wrong_password(self, client):
        """不存在的用户名与密码错误返回相同错误信息（防枚举攻击）。"""
        db = _make_db([None])  # user not found
        with _override_db(db):
            resp = await client.post(
                "/api/auth/login",
                json={"username": "noone", "password": "NoOne123"},
            )
        assert resp.status_code == 401
        assert "用户名或密码错误" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_disabled_user_returns_403(self, client):
        """禁用账户登录返回 403（区别于凭据错误 401）。"""
        user = _make_user(is_active=False)
        db = _make_db([user])
        with _override_db(db):
            resp = await client.post(
                "/api/auth/login",
                json={"username": _VALID_USERNAME, "password": _VALID_PASSWORD},
            )
        assert resp.status_code == 403
        assert "禁用" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_login_empty_username_returns_422(self, client):
        resp = await client.post(
            "/api/auth/login",
            json={"username": "", "password": _VALID_PASSWORD},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_login_missing_fields_returns_422(self, client):
        resp = await client.post("/api/auth/login", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_login_access_token_is_valid_jwt(self, client):
        """登录返回的 access token 可以用密钥解码，包含正确的 sub 字段。"""
        user = _make_user(user_id="fixed-uid-001")
        db = _make_db([user])
        settings = get_settings()
        with _override_db(db):
            resp = await client.post(
                "/api/auth/login",
                json={"username": _VALID_USERNAME, "password": _VALID_PASSWORD},
            )
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        assert payload["sub"] == "fixed-uid-001"
        assert payload["type"] == "access"


# ===========================================================================
# Layer 2 — API 测试：POST /api/auth/refresh
# ===========================================================================

class TestRefreshEndpoint:

    def _get_refresh_token_str(self, user_id: str = "user-123") -> tuple[str, str]:
        """生成一对合法的 (refresh_token_str, jti)。"""
        token_str, jti, _ = create_refresh_token(user_id)
        return token_str, jti

    @pytest.mark.asyncio
    async def test_refresh_success_returns_new_tokens(self, client):
        """有效的 refresh token 换取新的 token 对。"""
        user = _make_user(user_id="user-123")
        token_str, jti = self._get_refresh_token_str("user-123")
        rt_record = _make_rt_record(user_id="user-123", jti=jti, revoked=False)

        # execute 调用顺序：① 查 RefreshToken by jti  ② 查 User by id
        db = _make_db([rt_record, user])
        with _override_db(db):
            resp = await client.post(
                "/api/auth/refresh",
                json={"refresh_token": token_str},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        # 新旧 refresh token 不应相同（token rotation）
        assert data["refresh_token"] != token_str

    @pytest.mark.asyncio
    async def test_refresh_marks_old_token_revoked(self, client):
        """rotation 机制：旧 refresh token 被标记为 revoked=True。"""
        user = _make_user(user_id="user-123")
        token_str, jti = self._get_refresh_token_str("user-123")
        rt_record = _make_rt_record(user_id="user-123", jti=jti, revoked=False)

        db = _make_db([rt_record, user])
        with _override_db(db):
            await client.post(
                "/api/auth/refresh",
                json={"refresh_token": token_str},
            )
        # 验证旧 token 已被标记为 revoked
        assert rt_record.revoked is True

    @pytest.mark.asyncio
    async def test_refresh_with_revoked_token_returns_401(self, client):
        """已吊销的 token 被重用，返回 401。"""
        token_str, jti = self._get_refresh_token_str("user-123")
        rt_record = _make_rt_record(jti=jti, revoked=True)  # 已吊销

        # revoked 分支：① 查 token ② 查所有未吊销 token（批量吊销）
        db = _make_db([rt_record, []])  # 第二次查未吊销 token 返回空列表
        with _override_db(db):
            resp = await client.post(
                "/api/auth/refresh",
                json={"refresh_token": token_str},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_with_nonexistent_token_returns_401(self, client):
        """数据库里找不到 jti 对应记录，返回 401。"""
        token_str, _ = self._get_refresh_token_str()
        db = _make_db([None])  # 查不到 token 记录
        with _override_db(db):
            resp = await client.post(
                "/api/auth/refresh",
                json={"refresh_token": token_str},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_returns_401(self, client):
        """把 access token 误传给 refresh 端点，应被拒绝。"""
        access_token, _ = create_access_token("user-123")
        db = _make_db([])
        with _override_db(db):
            resp = await client.post(
                "/api/auth/refresh",
                json={"refresh_token": access_token},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_with_expired_jwt_returns_401(self, client):
        """JWT 本身已过期（exp 字段），应在 decode 阶段就被拒绝。"""
        settings = get_settings()
        payload = {
            "sub": "user-123",
            "jti": str(uuid.uuid4()),
            "type": "refresh",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),  # 已过期
        }
        expired_rt = jwt.encode(
            payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )
        db = _make_db([])
        with _override_db(db):
            resp = await client.post(
                "/api/auth/refresh",
                json={"refresh_token": expired_rt},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_refresh_disabled_user_revokes_old_token(self, client):
        """用户被禁用时，旧 refresh token 也会被吊销（不让禁用用户持有有效 token）。"""
        disabled_user = _make_user(user_id="user-123", is_active=False)
        token_str, jti = self._get_refresh_token_str("user-123")
        rt_record = _make_rt_record(jti=jti, revoked=False)

        db = _make_db([rt_record, disabled_user])
        with _override_db(db):
            resp = await client.post(
                "/api/auth/refresh",
                json={"refresh_token": token_str},
            )
        assert resp.status_code == 401
        # 旧 token 应已被吊销
        assert rt_record.revoked is True

    @pytest.mark.asyncio
    async def test_refresh_oversized_token_returns_422(self, client):
        """超过 max_length=2048 的 token 被 Pydantic 拒绝，不进入业务逻辑。"""
        resp = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": "x" * 2049},
        )
        assert resp.status_code == 422


# ===========================================================================
# Layer 2 — API 测试：POST /api/auth/logout
# ===========================================================================

class TestLogoutEndpoint:

    @pytest.mark.asyncio
    async def test_logout_success_returns_204(self, client):
        """有效 refresh token 登出后返回 204 No Content。"""
        token_str, jti = create_refresh_token("user-123")[:2]
        rt_record = _make_rt_record(jti=jti, revoked=False)

        db = _make_db([rt_record])
        with _override_db(db):
            resp = await client.post(
                "/api/auth/logout",
                json={"refresh_token": token_str},
            )
        assert resp.status_code == 204
        assert rt_record.revoked is True

    @pytest.mark.asyncio
    async def test_logout_invalid_token_returns_204_silently(self, client):
        """无效 token 登出时静默处理，不泄露信息，仍返回 204。"""
        db = _make_db([])
        with _override_db(db):
            resp = await client.post(
                "/api/auth/logout",
                json={"refresh_token": "not.a.valid.jwt.token"},
            )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_logout_already_revoked_token_returns_204(self, client):
        """已吊销的 token 再次登出，幂等处理，不报错。"""
        token_str, jti = create_refresh_token("user-123")[:2]
        rt_record = _make_rt_record(jti=jti, revoked=True)  # 已吊销

        db = _make_db([rt_record])
        with _override_db(db):
            resp = await client.post(
                "/api/auth/logout",
                json={"refresh_token": token_str},
            )
        assert resp.status_code == 204


# ===========================================================================
# Layer 2 — API 测试：GET /api/auth/me
# ===========================================================================

class TestMeEndpoint:

    @pytest.mark.asyncio
    async def test_me_with_valid_token(self, client):
        """有效 Bearer token 返回当前用户信息。"""
        user = _make_user(user_id="me-user-001", username="meuser")
        access_token, _ = create_access_token("me-user-001")

        db = _make_db([user])
        with _override_db(db):
            resp = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "meuser"
        assert data["id"] == "me-user-001"
        assert "hashed_password" not in data

    @pytest.mark.asyncio
    async def test_me_without_token_returns_401(self, client):
        """不带 token 的请求返回 401。"""
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_expired_token_returns_401(self, client):
        """过期 access token 返回 401。"""
        settings = get_settings()
        expired_payload = {
            "sub": "user-123",
            "type": "access",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        expired_token = jwt.encode(
            expired_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )
        db = _make_db([])
        with _override_db(db):
            resp = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {expired_token}"},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_with_refresh_token_returns_401(self, client):
        """用 refresh token 调用 /me，类型校验不通过，返回 401。"""
        rt, _, _ = create_refresh_token("user-123")
        db = _make_db([])
        with _override_db(db):
            resp = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {rt}"},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_nonexistent_user_returns_401(self, client):
        """token 合法但用户已被删除，返回 401。"""
        access_token, _ = create_access_token("deleted-user")
        db = _make_db([None])  # 查不到用户
        with _override_db(db):
            resp = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_me_disabled_user_returns_403(self, client):
        """禁用用户的 token 仍然有效签名，但业务层返回 403。"""
        user = _make_user(user_id="disabled-001", is_active=False)
        access_token, _ = create_access_token("disabled-001")

        db = _make_db([user])
        with _override_db(db):
            resp = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        assert resp.status_code == 403


# ===========================================================================
# Layer 2 — 安全场景组合测试
# ===========================================================================

class TestSecurityScenarios:
    """跨端点的安全场景验证。"""

    @pytest.mark.asyncio
    async def test_login_then_use_access_token(self, client):
        """完整流程：登录拿到 token，再用 token 访问受保护端点。"""
        user = _make_user(user_id="flow-user-001")

        # 第一步：登录
        login_db = _make_db([user])
        with _override_db(login_db):
            login_resp = await client.post(
                "/api/auth/login",
                json={"username": _VALID_USERNAME, "password": _VALID_PASSWORD},
            )
        assert login_resp.status_code == 200
        access_token = login_resp.json()["access_token"]

        # 第二步：用 access token 访问 /me
        me_db = _make_db([user])
        with _override_db(me_db):
            me_resp = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        assert me_resp.status_code == 200
        assert me_resp.json()["id"] == "flow-user-001"

    @pytest.mark.asyncio
    async def test_full_token_rotation_flow(self, client):
        """完整 Token Rotation 流程：refresh 后旧 token 作废，新 token 有效。"""
        user = _make_user(user_id="rotation-user")
        token_str, jti = create_refresh_token("rotation-user")[:2]
        rt_record = _make_rt_record(user_id="rotation-user", jti=jti)

        # refresh
        db = _make_db([rt_record, user])
        with _override_db(db):
            resp = await client.post(
                "/api/auth/refresh",
                json={"refresh_token": token_str},
            )
        assert resp.status_code == 200
        new_refresh_token = resp.json()["refresh_token"]

        # 验证新旧 token 不同
        assert new_refresh_token != token_str
        # 验证旧 token 已被标记作废
        assert rt_record.revoked is True

    @pytest.mark.asyncio
    async def test_tampered_token_rejected_on_me_endpoint(self, client):
        """篡改 token payload（修改 user_id），验证签名失败被拒绝。"""
        access_token, _ = create_access_token("real-user")
        # 解码 + 篡改 + 用错误密钥重新签名
        parts = access_token.split(".")
        import base64, json as _json
        fake_payload = {"sub": "admin", "type": "access", "exp": 9999999999}
        fake_b64 = base64.urlsafe_b64encode(
            _json.dumps(fake_payload).encode()
        ).rstrip(b"=").decode()
        tampered_token = f"{parts[0]}.{fake_b64}.{parts[2]}"

        db = _make_db([])
        with _override_db(db):
            resp = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {tampered_token}"},
            )
        assert resp.status_code == 401
