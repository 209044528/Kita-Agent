import sys
import os
from loguru import logger
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.trigger.http import chat_controller, maintenance_controller
from app.core.exceptions import KitaBaseException
from app.types.response import Response
import uvicorn

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

app = FastAPI(
    title="Kita-Agent API",
    description="基于 DDD 架构的 ReAct 智能体服务",
    version="1.0.0"
)

# --- 2. 全局异常处理 ---
@app.exception_handler(KitaBaseException)
async def kita_exception_handler(request: Request, exc: KitaBaseException):
    logger.error(f"业务异常: code={exc.code}, info={exc.info}, data={exc.data}")
    return JSONResponse(
        status_code=200,  # 业务异常返回 200，由业务 code 区分
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
    allow_origins=["*"],
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
app.mount("/", StaticFiles(directory="web", html=True), name="web")

if __name__ == "__main__":
    logger.info("🚀 正在启动 Kita-Agent FastAPI 服务...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
