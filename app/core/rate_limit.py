import time
from fastapi import Request, HTTPException
from redis import Redis
from app.core.config import settings

redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)

async def rate_limit_by_ip(request: Request, max_requests: int = 10, window_seconds: int = 60):
    """
    基于客户端 IP 的 Redis 限流依赖函数

    Args:
        request: FastAPI 请求对象
        max_requests: 时间窗口内最大请求数
        window_seconds: 时间窗口（秒）

    Raises:
        HTTPException: 触发限流时抛出 429 异常
    """
    client_ip = request.client.host if request.client else "unknown"

    rate_limit_key = f"rate_limit:{client_ip}"
    current_time = int(time.time())
    window_start = current_time - window_seconds

    pipe = redis_client.pipeline()
    pipe.zremrangebyscore(rate_limit_key, 0, window_start)
    pipe.zadd(rate_limit_key, {str(current_time): current_time})
    pipe.zcard(rate_limit_key)
    pipe.expire(rate_limit_key, window_seconds)

    results = pipe.execute()
    request_count = results[2]

    if request_count > max_requests:
        raise HTTPException(
            status_code=429,
            detail=f"请求过于频繁，每 {window_seconds} 秒最多 {max_requests} 次请求"
        )
