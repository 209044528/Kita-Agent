import uvicorn
import logging
import os
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.trigger.http import chat_controller, maintenance_controller
from fastapi.responses import FileResponse

# 配置日志
LOG_DIR = "logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

log_filename = f"kita_agent_{datetime.now().strftime('%Y%m%d')}.log"
log_path = os.path.join(LOG_DIR, log_filename)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_path, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Kita-Agent API",
    description="基于 DDD 架构 de ReAct 智能体服务",
    version="1.0.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 基础健康检查接口
@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok", "message": "Kita-Agent 服务正在运行"}

@app.get("/chat/{session_id}", tags=["System"])
async def chat_page(session_id: str):
    return FileResponse("web/index.html")

app.include_router(chat_controller.router, prefix="/api/v1", tags=["Agent Chat"])
app.include_router(maintenance_controller.router, prefix="/api/v1", tags=["Maintenance"])
app.mount("/", StaticFiles(directory="web", html=True), name="web")

if __name__ == "__main__":
    logger.info("🚀 正在启动 Kita-Agent FastAPI 服务...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)