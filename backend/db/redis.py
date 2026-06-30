"""Redis integration."""

from typing import Protocol, cast

from redis.asyncio import Redis


class RedisLike(Protocol):
    """Subset of Redis commands used by the request admission path."""

    async def ping(self) -> bool: ...

    async def get(self, name: str) -> object | None: ...

    async def set(self, name: str, value: object, ex: int | None = None) -> object: ...

    async def incr(self, name: str) -> int: ...

    async def incrby(self, name: str, amount: int) -> int: ...

    async def decr(self, name: str) -> int: ...

    async def decrby(self, name: str, amount: int) -> int: ...

    async def expire(self, name: str, time: int) -> object: ...

    async def delete(self, *names: str) -> int: ...

    async def rpush(self, name: str, value: str) -> int: ...

    async def lpop(self, name: str) -> object | None: ...

    async def lrange(self, name: str, start: int, end: int) -> list[object]: ...

    async def aclose(self) -> None: ...


class RedisClient:
    """Application Redis client wrapper."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @classmethod
    def from_url(cls, redis_url: str) -> "RedisClient":
        return cls(Redis.from_url(redis_url, decode_responses=True))

    async def ping(self) -> bool:
        return bool(await self._redis.ping())

    async def get(self, name: str) -> object | None:
        return await self._redis.get(name)

    async def set(self, name: str, value: object, ex: int | None = None) -> object:
        redis_value = cast(bytes | bytearray | str | int | float, value)
        return await self._redis.set(name, redis_value, ex=ex)

    async def incr(self, name: str) -> int:
        return int(await self._redis.incr(name))

    async def decr(self, name: str) -> int:
        return int(await self._redis.decr(name))

    async def incrby(self, name: str, amount: int) -> int:
        return int(await self._redis.incrby(name, amount))

    async def decrby(self, name: str, amount: int) -> int:
        return int(await self._redis.decrby(name, amount))

    async def expire(self, name: str, time: int) -> object:
        return await self._redis.expire(name, time)

    async def delete(self, *names: str) -> int:
        return int(await self._redis.delete(*names))

    async def rpush(self, name: str, value: str) -> int:
        return int(await self._redis.rpush(name, value))

    async def lpop(self, name: str) -> object | None:
        return await self._redis.lpop(name)

    async def lrange(self, name: str, start: int, end: int) -> list[object]:
        return list(await self._redis.lrange(name, start, end))

    async def aclose(self) -> None:
        await self._redis.aclose()
