import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.trigger.http import chat_controller

app = FastAPI(
    title="Kita-Agent API",
    description="基于 DDD 架构的 ReAct 智能体服务",
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

app.include_router(chat_controller.router, prefix="/api/v1", tags=["Agent Chat"])
app.mount("/", StaticFiles(directory="web", html=True), name="web")

if __name__ == "__main__":
    print("🚀 正在启动 Kita-Agent FastAPI 服务...")
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)