"""
缓存模块：Redis Cache-Aside + TTL，并在 Redis 不可用时降级到本地内存缓存。

使用场景（当前工程）：
- 首页 / 驾驶舱 / 运维等高频 GET 接口（KPI、近期告警、趋势查询）

关键点：
- Cache-Aside：先读缓存，miss 再回源计算，再写回缓存（设置 TTL）
- Stampede control：同一 cache key 只允许一个请求回源，其他请求短等待后重读缓存
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime
import time
import uuid
from collections import OrderedDict
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional, TypeVar

from app.core.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class LocalTTLCache:
    """
    极简 LRU + TTL 内存缓存。
    - 避免引入额外依赖（如 cachetools）
    - 仅用于 Redis 不可用时的短期兜底
    """

    def __init__(self, maxsize: int = 1024, default_ttl_seconds: int = 60) -> None:
        self._maxsize = maxsize
        self._default_ttl_seconds = default_ttl_seconds
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        now = time.time()
        async with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._data.pop(key, None)
                return None

            # LRU 访问更新
            self._data.move_to_end(key)
            return value

    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        expires_at = time.time() + max(1, int(ttl))
        async with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = (expires_at, value)
            while len(self._data) > self._maxsize:
                # FIFO in OrderedDict => LRU
                self._data.popitem(last=False)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def delete_by_prefix(self, prefix: str) -> None:
        async with self._lock:
            keys = [k for k in self._data.keys() if k.startswith(prefix)]
            for k in keys:
                self._data.pop(k, None)


_local_cache: Optional[LocalTTLCache] = None
_redis_client: Any = None  # redis.asyncio.Redis
_redis_lock = asyncio.Lock()

# 本地 stampede control：每个 key 一个锁
_local_key_locks: dict[str, asyncio.Lock] = {}
_local_key_locks_lock = asyncio.Lock()


async def init_redis_client() -> None:
    """在应用启动时调用，初始化 Redis client（失败时仍允许本地降级）。"""
    global _redis_client
    settings = get_settings()

    async with _redis_lock:
        if _redis_client is not None:
            return

        try:
            # 延迟导入，避免 Redis 包未安装时影响其它功能
            import redis.asyncio as redis_async

            _redis_client = redis_async.from_url(
                settings.REDIS_URL,
                decode_responses=True,  # 让 get/set 直接处理 str
            )

            # 简单 ping 验证连接可用性
            await _redis_client.ping()
            logger.info("Redis cache 初始化成功：%s", settings.REDIS_URL)
        except Exception as exc:
            _redis_client = None
            logger.warning("Redis cache 初始化失败，进入本地降级：%s", exc)

        # 初始化本地兜底缓存
        global _local_cache
        _local_cache = LocalTTLCache(
            maxsize=settings.CACHE_LOCAL_MAXSIZE,
            default_ttl_seconds=settings.CACHE_LOCAL_DEFAULT_TTL_SECONDS,
        )


async def close_redis_client() -> None:
    """在应用关闭时调用，释放 Redis 连接。"""
    global _redis_client
    async with _redis_lock:
        if _redis_client is None:
            return
        try:
            await _redis_client.aclose()
        except Exception:
            logger.exception("Redis client close 异常")
        finally:
            _redis_client = None


def _bucket_seconds() -> int:
    return get_settings().CACHE_BUCKET_SECONDS


def cache_bucket(now_ts: Optional[float] = None) -> int:
    """30 秒时间桶：用于 overview/anomalies 的 key 粒度。"""
    now = now_ts if now_ts is not None else time.time()
    return int(now // _bucket_seconds())


async def _get_local_cache() -> LocalTTLCache:
    global _local_cache
    if _local_cache is None:
        # 理论上 init_redis_client 会初始化；但为了更稳健，这里兜底
        await init_redis_client()
    if _local_cache is None:
        raise RuntimeError("LocalTTLCache 未初始化，请确认 init_redis_client() 已在应用启动时调用")
    return _local_cache


async def _get_from_redis(key: str) -> Optional[Any]:
    if _redis_client is None:
        return None
    try:
        raw = await _redis_client.get(key)
        if raw is None:
            logger.debug("[cache] miss redis key=%s", key)
            return None
        logger.debug("[cache] hit redis key=%s", key)
        return json.loads(raw)
    except Exception:
        logger.debug("Redis get 失败，回退本地：key=%s", key, exc_info=True)
        return None


async def _set_to_redis(key: str, value: Any, ttl_seconds: int) -> None:
    if _redis_client is None:
        return
    try:
        # Redis 只存字符串；当前业务返回值可能包含 Decimal/date/datetime，
        # 需要显式转换，避免 json.dumps 失败导致整次写入被忽略。
        def _json_default(obj: Any) -> Any:
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()
            if isinstance(obj, Decimal):
                # 用 float 进入前端计算/展示；若精度有要求再改为 str
                return float(obj)
            return str(obj)

        raw = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        )
        await _redis_client.set(key, raw, ex=ttl_seconds)
        logger.debug("[cache] set redis key=%s ttl=%ss", key, ttl_seconds)
    except Exception:
        logger.debug("Redis set 失败，忽略：key=%s", key, exc_info=True)


async def _acquire_redis_lock(lock_key: str, lock_value: str, expire_seconds: int) -> bool:
    if _redis_client is None:
        return False
    try:
        # SET key value NX EX seconds
        ok = await _redis_client.set(lock_key, lock_value, nx=True, ex=expire_seconds)
        return bool(ok)
    except Exception:
        return False


async def _release_redis_lock(lock_key: str, lock_value: str) -> None:
    if _redis_client is None:
        return
    # token 校验删除：避免误删其它请求持有的锁
    try:
        lua = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        else
            return 0
        end
        """
        await _redis_client.eval(lua, 1, lock_key, lock_value)
    except Exception:
        logger.debug("Redis unlock 失败：%s", lock_key, exc_info=True)


async def delete_cache_key(cache_key: str) -> None:
    """删除单个缓存 key（同时清理本地与 Redis）。"""
    cache = await _get_local_cache()
    await cache.delete(cache_key)
    logger.info("[cache] delete local key=%s", cache_key)
    if _redis_client is not None:
        try:
            await _redis_client.delete(cache_key)
            logger.info("[cache] delete redis key=%s", cache_key)
        except Exception:
            logger.debug("Redis delete 失败：%s", cache_key, exc_info=True)


async def delete_cache_by_prefix(prefix: str) -> None:
    """按前缀批量删除缓存（用于会话/工单变更后的失效）。"""
    cache = await _get_local_cache()
    await cache.delete_by_prefix(prefix)
    logger.info("[cache] delete local prefix=%s*", prefix)

    if _redis_client is None:
        return

    try:
        cursor = 0
        pattern = f"{prefix}*"
        total_deleted = 0
        while True:
            cursor, keys = await _redis_client.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                deleted = await _redis_client.delete(*keys)
                total_deleted += int(deleted or 0)
            if cursor == 0:
                break
        logger.info("[cache] delete redis prefix=%s* deleted=%d", prefix, total_deleted)
    except Exception:
        logger.debug("Redis delete_by_prefix 失败：%s", prefix, exc_info=True)


async def _get_from_local(key: str) -> Optional[Any]:
    cache = await _get_local_cache()
    value = await cache.get(key)
    if value is None:
        logger.debug("[cache] miss local key=%s", key)
    else:
        logger.debug("[cache] hit local key=%s", key)
    return value


async def _set_to_local(key: str, value: Any, ttl_seconds: int) -> None:
    cache = await _get_local_cache()
    await cache.set(key, value, ttl_seconds=ttl_seconds)
    logger.debug("[cache] set local key=%s ttl=%ss", key, ttl_seconds)


async def get_or_compute_json(
    cache_key: str,
    ttl_seconds: int,
    compute: Callable[[], Awaitable[T]],
) -> T:
    """
    读取缓存，没有则 stampede control 回源计算，并写回缓存。
    返回值类型以 JSON 序列化的结果为准（dict/list/number 等）。
    """
    settings = get_settings()

    # 先读本地（比 Redis 更快，且能减少 Redis 压力）
    local_hit = await _get_from_local(cache_key)
    if local_hit is not None:
        return local_hit  # type: ignore[return-value]

    # 再读 Redis
    redis_hit = await _get_from_redis(cache_key)
    if redis_hit is not None:
        # 回填本地，提升后续命中
        await _set_to_local(cache_key, redis_hit, ttl_seconds=ttl_seconds)
        return redis_hit  # type: ignore[return-value]

    # miss：Redis 可用时走分布式锁；不可用时降级为本地锁（避免 1s 全局等待 + thundering herd）
    if _redis_client is None:
        logger.debug("[cache] redis unavailable, fallback local lock key=%s", cache_key)
        local_lock = await _local_key_lock(cache_key)
        async with local_lock:
            local_hit2 = await _get_from_local(cache_key)
            if local_hit2 is not None:
                return local_hit2  # type: ignore[return-value]
            logger.info("[cache] recompute (local-lock) key=%s", cache_key)
            value = await compute()
            await _set_to_local(cache_key, value, ttl_seconds=ttl_seconds)
            return value

    lock_key = f"lock:{cache_key}"
    lock_value = uuid.uuid4().hex

    got_lock = await _acquire_redis_lock(
        lock_key=lock_key,
        lock_value=lock_value,
        expire_seconds=settings.CACHE_LOCK_EXPIRE_SECONDS,
    )

    if not got_lock:
        logger.info("[cache] lock busy key=%s wait=%ss", cache_key, settings.CACHE_LOCK_WAIT_SECONDS)
        # 没拿到 lock：短等待后重读（尽量避免多个请求同时回源）
        await asyncio.sleep(float(settings.CACHE_LOCK_WAIT_SECONDS))

        local_hit2 = await _get_from_local(cache_key)
        if local_hit2 is not None:
            return local_hit2  # type: ignore[return-value]

        redis_hit2 = await _get_from_redis(cache_key)
        if redis_hit2 is not None:
            await _set_to_local(cache_key, redis_hit2, ttl_seconds=ttl_seconds)
            return redis_hit2  # type: ignore[return-value]

        # 仍然 miss：兜底直接回源（极端情况下允许少量重复计算）
        logger.info("[cache] recompute fallback key=%s", cache_key)
        value = await compute()
        await _set_to_local(cache_key, value, ttl_seconds=ttl_seconds)
        await _set_to_redis(cache_key, value, ttl_seconds=ttl_seconds)
        return value

    # 拿到 lock 的请求：负责回源并写回
    try:
        logger.info("[cache] recompute primary key=%s", cache_key)
        value = await compute()
        await _set_to_local(cache_key, value, ttl_seconds=ttl_seconds)
        await _set_to_redis(cache_key, value, ttl_seconds=ttl_seconds)
        return value
    finally:
        await _release_redis_lock(lock_key=lock_key, lock_value=lock_value)


async def get_or_compute_local_json(
    cache_key: str,
    ttl_seconds: int,
    compute: Callable[[], Awaitable[T]],
) -> T:
    """
    纯本地降级回源（当 Redis 初始化失败/未配置时可用）。
    不提供跨实例 stampede control，但能避免单实例重复回源。
    """
    local_hit = await _get_from_local(cache_key)
    if local_hit is not None:
        return local_hit  # type: ignore[return-value]

    lock = await _local_key_lock(cache_key)
    async with lock:
        # double-check（防并发）
        local_hit2 = await _get_from_local(cache_key)
        if local_hit2 is not None:
            return local_hit2  # type: ignore[return-value]

        value = await compute()
        await _set_to_local(cache_key, value, ttl_seconds=ttl_seconds)
        return value


async def _local_key_lock(cache_key: str) -> asyncio.Lock:
    async with _local_key_locks_lock:
        lock = _local_key_locks.get(cache_key)
        if lock is None:
            lock = asyncio.Lock()
            _local_key_locks[cache_key] = lock
        return lock

