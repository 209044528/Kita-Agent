import sys
import os

# 禁用 LiteLLM 遥测和远程价格表拉取（必须在所有业务 import 之前设置）
os.environ["LITELLM_TELEMETRY"] = "False"
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import mimetypes
from contextlib import asynccontextmanager
from loguru import logger
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.trigger.http import (
    chat_controller,
    maintenance_controller,
    observability_controller,
    platform_controller,
)
from app.core.exceptions import KitaBaseException
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.config import settings
from app.core.security import resolve_api_key
from app.core.container import get_tool_registry
from app.infrastructure.mcp import create_mcp_server
from app.types.response import Response
import uvicorn

# 确保 .js 文件在 Windows 等环境下返回正确的 MIME 类型
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')

# --- 1. 初始化 Loguru 日志 ---
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# 配置控制台与文件输出
logger.remove()  # 移除默认处理器
logger.add(
    sys.stdout, 
    level="INFO", 
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:7}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)
logger.add(
    os.path.join(LOG_DIR, "kita_agent_{time:YYYY-MM-DD}.log"),
    rotation="00:00",      # 每天凌晨切割
    retention="10 days",   # 保留 10 天
    level="INFO",
    encoding="utf-8",
    enqueue=True           # 异步写入
)

mcp_server = None
mcp_app = None
if settings.MCP_ENABLED:
    try:
        mcp_server = create_mcp_server(get_tool_registry())
        mcp_app = mcp_server.streamable_http_app()
    except RuntimeError as exc:
        logger.warning(str(exc))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if mcp_server:
        async with mcp_server.session_manager.run():
            yield
    else:
        yield


app = FastAPI(
    title="Kita-Agent API",
    description="基于 DDD 架构的 ReAct 智能体服务",
    version="1.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def protect_mcp(request: Request, call_next):
    if settings.AUTH_ENABLED and request.url.path.startswith("/mcp"):
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "缺少 Bearer API Key"})
        try:
            resolve_api_key(authorization.removeprefix("Bearer ").strip())
        except AuthenticationError as exc:
            return JSONResponse(status_code=401, content={"detail": exc.info})
    return await call_next(request)

# --- 2. 全局异常处理 ---
@app.exception_handler(KitaBaseException)
async def kita_exception_handler(request: Request, exc: KitaBaseException):
    logger.error(f"业务异常: code={exc.code}, info={exc.info}, data={exc.data}")
    if isinstance(exc, AuthenticationError):
        status_code = 401
    elif isinstance(exc, AuthorizationError):
        status_code = 403
    else:
        status_code = 200
    return JSONResponse(
        status_code=status_code,
        content=Response.error(code=exc.code, info=exc.info, data=exc.data).model_dump()
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("未捕获的全局异常")
    return JSONResponse(
        status_code=500,
        content=Response.error(code="9999", info=f"服务器内部错误: {str(exc)}").model_dump()
    )

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 基础健康检查接口
@app.get("/health", tags=["System"], response_model=Response[str])
async def health_check():
    return Response.success(info="Kita-Agent 服务正在运行")

@app.get("/chat/{session_id}", tags=["System"])
async def chat_page(session_id: str):
    return FileResponse("web/index.html")

app.include_router(chat_controller.router, prefix="/api/v1", tags=["Agent Chat"])
app.include_router(maintenance_controller.router, prefix="/api/v1", tags=["Maintenance"])
app.include_router(observability_controller.router, prefix="/api/v1", tags=["Observability"])
app.include_router(platform_controller.router, prefix="/api/v1", tags=["Platform"])
if mcp_app:
    @app.api_route(
        "/mcp",
        methods=["GET", "POST", "DELETE"],
        include_in_schema=False,
    )
    async def redirect_mcp():
        return RedirectResponse(url="/mcp/", status_code=307)

    app.mount("/mcp", mcp_app, name="mcp")
app.mount("/", StaticFiles(directory="web", html=True), name="web")

if __name__ == "__main__":
    logger.info("🚀 正在启动 Kita-Agent FastAPI 服务...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
