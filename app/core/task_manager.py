from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

import redis.asyncio as redis

from app.core.config import settings
from app.core.exceptions import AuthorizationError, SessionBusyError
from app.core.security import RequestIdentity


@dataclass
class TaskRecord:
    task_id: str
    user_id: str
    session_id: str
    cancel_event: asyncio.Event
    runner_task: asyncio.Task | None = None


class AgentTaskManager:
    def __init__(self):
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self._tasks: dict[str, TaskRecord] = {}
        self._guard = asyncio.Lock()

    def new_task_id(self) -> str:
        return uuid.uuid4().hex

    def _task_key(self, task_id: str) -> str:
        return f"kita:agent:task:{task_id}"

    def _cancel_key(self, task_id: str) -> str:
        return f"kita:agent:task:{task_id}:cancelled"

    def _session_lock_key(self, user_id: str, session_id: str) -> str:
        return f"kita:agent:lock:{user_id}:{session_id}"

    @asynccontextmanager
    async def run(
        self,
        task_id: str,
        identity: RequestIdentity,
        session_id: str,
    ):
        lock_key = self._session_lock_key(identity.user_id, session_id)
        acquired = await self.redis.set(
            lock_key,
            task_id,
            ex=settings.SESSION_LOCK_TTL_SECONDS,
            nx=True,
        )
        if not acquired:
            raise SessionBusyError()

        record = TaskRecord(
            task_id=task_id,
            user_id=identity.user_id,
            session_id=session_id,
            cancel_event=asyncio.Event(),
            runner_task=asyncio.current_task(),
        )
        async with self._guard:
            self._tasks[task_id] = record
        await self.redis.setex(
            self._task_key(task_id),
            settings.TASK_TTL_SECONDS,
            json.dumps(
                {"user_id": identity.user_id, "session_id": session_id},
                ensure_ascii=False,
            ),
        )
        watcher = asyncio.create_task(self._watch_remote_cancel(record))
        heartbeat = asyncio.create_task(
            self._keep_lock_alive(lock_key, task_id)
        )
        try:
            yield record
        finally:
            watcher.cancel()
            heartbeat.cancel()
            await asyncio.gather(watcher, heartbeat, return_exceptions=True)
            async with self._guard:
                self._tasks.pop(task_id, None)
            await self._release_lock(lock_key, task_id)
            await self.redis.delete(self._task_key(task_id), self._cancel_key(task_id))

    async def cancel(self, task_id: str, identity: RequestIdentity) -> bool:
        metadata = await self.redis.get(self._task_key(task_id))
        if not metadata:
            return False
        task_data = json.loads(metadata)
        if task_data.get("user_id") != identity.user_id and not identity.is_admin:
            raise AuthorizationError("不能取消其他用户的任务")

        await self.redis.setex(
            self._cancel_key(task_id), settings.TASK_TTL_SECONDS, "1"
        )
        async with self._guard:
            record = self._tasks.get(task_id)
            if record:
                record.cancel_event.set()
                if record.runner_task and record.runner_task is not asyncio.current_task():
                    record.runner_task.cancel()
        return True

    async def is_cancelled(self, task_id: str) -> bool:
        async with self._guard:
            record = self._tasks.get(task_id)
            if record and record.cancel_event.is_set():
                return True
        return bool(await self.redis.exists(self._cancel_key(task_id)))

    async def _watch_remote_cancel(self, record: TaskRecord) -> None:
        try:
            while not record.cancel_event.is_set():
                if await self.redis.exists(self._cancel_key(record.task_id)):
                    record.cancel_event.set()
                    if record.runner_task:
                        record.runner_task.cancel()
                    return
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            return

    async def _release_lock(self, key: str, task_id: str) -> None:
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
          return redis.call("del", KEYS[1])
        end
        return 0
        """
        await self.redis.eval(script, 1, key, task_id)

    async def _keep_lock_alive(self, key: str, task_id: str) -> None:
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
          return redis.call("expire", KEYS[1], ARGV[2])
        end
        return 0
        """
        interval = max(1, settings.SESSION_LOCK_TTL_SECONDS // 3)
        try:
            while True:
                await asyncio.sleep(interval)
                renewed = await self.redis.eval(
                    script,
                    1,
                    key,
                    task_id,
                    settings.SESSION_LOCK_TTL_SECONDS,
                )
                if not renewed:
                    return
        except asyncio.CancelledError:
            return
