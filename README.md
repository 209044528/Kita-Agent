# Kita-Agent

Kita-Agent 是一个基于 **ReAct 推理循环 + RAG 知识库 + FastAPI SSE 流式接口** 的轻量级 AI Agent 项目。  
本项目不依赖 LangChain Agent / CrewAI 等高层封装，而是通过手写核心逻辑理解大语言模型驱动智能体的 **“思考 → 工具调用 → 观察 → 再规划 → 最终回答”** 流程。

项目定位不是普通 Chatbot，而是一个可扩展的 Agent 后端原型：  
- 面向知识库问答场景，支持文档入库、标签化检索、向量召回、可选 reranker 重排；
- 面向 Agent 工程实践，支持 ReAct 格式约束、工具注册、参数校验、工具执行与失败纠偏；
- 面向实际部署，提供 FastAPI 接口、SSE 流式输出、Web UI、Docker Compose 和本地模型服务。

---

## 目录

- [项目亮点](#项目亮点)
- [系统架构](#系统架构)
- [Agent 执行流程](#agent-执行流程)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [快速启动](#快速启动)
- [环境变量](#环境变量)
- [日志与维护](#日志与维护)
- [已完成的工程化升级](#已完成的工程化升级)

---

## 项目亮点

### 1. 手写 ReAct 推理循环

项目在领域层实现 Agent 聚合根，由 Agent 自身维护多轮消息、系统提示词和 ReAct 推理过程。  
模型每轮输出一个结构化动作：

```json
{
  "thought": "需要检索知识库",
  "tool": "knowledge_search",
  "arguments": {
    "query": "ReAct Agent",
    "tag": "agent-basic"
  }
}
```

最终回答使用 `tool: "finish"` 和 `arguments.answer`。Agent 优先解析 JSON，
同时兼容旧版 `Action: knowledge_search(...)` / `Finish[...]`：

- JSON Schema 校验失败：写入 Observation 纠偏提示；
- 未知工具或执行失败：返回可观测的结构化错误；
- 输出格式异常：写入 Observation 纠偏提示，要求模型重新按格式输出；
- 超过最大推理步数：强制终止，避免无限循环。

---

### 2. 可扩展 Tool Registry 工具注册机制

项目抽象了统一的 `BaseTool` 与 `ToolRegistry`：

- 每个工具声明名称、描述和参数；
- 启动时将工具注册到工具中心；
- Agent 只关心工具名称和参数，不直接依赖具体实现；
- 工具调用前进行参数校验；
- 工具执行失败时返回结构化错误信息，进入下一轮 ReAct 纠偏。
- 同一份注册信息可生成 JSON Schema、OpenAI Function Calling 定义和 MCP Tool。

当前已接入：

```text
knowledge_search(query="检索关键词", tag="知识标签")
```

后续可以在此基础上扩展：

```text
web_search(query="...")
code_reader(path="...")
vision_detect(object="tennis_ball")
world_model_query(object_id="...")
robot_action(action="scan")
```

---

### 3. RAG 知识库问答链路

知识库模块支持从原始文本、本地文件或 Git 仓库解析内容，并进行向量化入库。  
当前检索流程包括：

1. Markdown 标题切分；
2. 递归文本切分；
3. 注入 `knowledge_tag`、`source`、`chunk_hash` 等元数据；
4. 向量数据库持久化；
5. 初步相似度召回；
6. 可选 BGE reranker 重排；
7. 拼接 Top-K 文档作为 Agent Observation。

---

### 4. FastAPI + SSE 流式输出

项目通过 FastAPI 提供 Agent HTTP 接口，并使用 SSE 返回流式内容：

```text
data: {"content": "正在思考..."}
data: {"content": "✓ 已找到相关信息"}
data: {"content": "最终回答内容"}
data: [DONE]
```

这使前端可以实时展示 Agent 的推理进度和回答结果，而不是等待完整响应结束。

---

### 5. Clean Architecture / DDD 分层

项目采用偏 Clean Architecture 的目录组织：

- `domain`：Agent、Memory、Tool 等核心领域模型；
- `application`：用例编排，例如对话服务、知识库服务；
- `infrastructure`：LLM、Redis、PostgreSQL、向量库等外部依赖实现；
- `trigger`：HTTP Controller；
- `types`：请求与响应 DTO。

这种结构使 Agent 逻辑和具体框架解耦，后续替换模型、向量库、工具实现时影响较小。

---

### 6. 本地化与容器化部署

项目支持通过 Docker Compose 管理：

- Kita-Agent FastAPI 服务；
- Redis；
- PostgreSQL / pgvector；
- Ollama；
- reranker 服务。

适合在本地完成 Agent 原型开发、RAG 知识库验证和模型切换实验。

---

## 系统架构

```mermaid
flowchart TD
    U[用户 / Web UI / API Client] -->|HTTP / SSE| API[FastAPI Trigger Layer]

    API --> APP[Application Service<br/>ChatAppService / KnowledgeAppService]

    APP --> AGENT[Domain: AgentEntity<br/>ReAct Loop]
    AGENT --> PROMPT[Prompt Builder<br/>Persona + ReAct Instruction]
    AGENT --> TOOLREG[ToolRegistry]

    TOOLREG --> KTOOL[KnowledgeSearchTool]
    KTOOL --> KAPP[KnowledgeAppService]
    KAPP --> SPLIT[Markdown + Recursive Splitter]
    KAPP --> VDB[(PostgreSQL / pgvector)]
    KAPP --> RERANK[Reranker Service<br/>Optional]

    AGENT --> LLM[LLM Client<br/>LiteLLM / OpenAI / Ollama / GLM]
    APP --> REPO[Agent Repository<br/>Session / Prompt / Memory]

    REPO --> REDIS[(Redis)]
    API --> WEB[Static Web UI]
```

---

## Agent 执行流程

```mermaid
sequenceDiagram
    participant User
    participant API as FastAPI /chat/stream
    participant App as ChatAppService
    participant Agent as AgentEntity
    participant Tool as ToolRegistry
    participant KB as KnowledgeService
    participant LLM as LLM Client

    User->>API: POST /api/v1/chat/stream
    API->>App: do_stream_chat(session_id, user_input)
    App->>Agent: 加载会话 / 构建系统提示词
    Agent->>LLM: 请求下一步结构化动作
    LLM-->>Agent: {"tool":"knowledge_search","arguments":{...}}
    Agent->>Tool: execute("knowledge_search", args)
    Tool->>KB: retrieve_knowledge(query, tag)
    KB-->>Tool: 检索上下文
    Tool-->>Agent: Observation
    Agent->>LLM: 携带 Observation 继续推理
    LLM-->>Agent: {"tool":"finish","arguments":{"answer":"..."}}
    Agent-->>API: SSE 流式返回内容
    API-->>User: data: {"content": "..."}
```

---

## 技术栈

| 类别 | 技术 |
|---|---|
| 后端框架 | FastAPI |
| Agent 范式 | ReAct |
| LLM 接入 | LiteLLM、OpenAI 兼容接口、Ollama、本地 Qwen |
| RAG | MarkdownHeaderTextSplitter、RecursiveCharacterTextSplitter、向量检索、reranker |
| 工具协议 | JSON Schema、Function Calling、MCP Streamable HTTP / stdio |
| 可观测性 | JSONL Trace、工具耗时指标、bad case、RAG 评测 |
| 数据存储 | Redis、PostgreSQL / pgvector |
| 工具机制 | BaseTool、ToolRegistry、参数校验 |
| 前端 | 原生 Web 静态页面 |
| 部署 | Docker、Docker Compose |
| 日志 | Loguru |
| 语言 | Python 3.12+ |

---

## 项目结构

```text
Kita-Agent/
├── app/
│   ├── application/
│   │   └── services/
│   │       ├── chat_app_service.py              # 对话用例编排
│   │       ├── knowledge_app_service.py         # 知识库入库、检索、重排
│   │       └── document_parser_service.py       # 文档解析服务
│   ├── core/
│   │   ├── config.py                            # 配置
│   │   ├── container.py                         # 依赖注入
│   │   ├── exceptions.py                        # 自定义异常
│   │   └── rate_limit.py                        # 限流
│   ├── domain/
│   │   ├── agent/
│   │   │   ├── entity.py                        # Agent 聚合根与 ReAct 循环
│   │   │   ├── prompt.py                        # ReAct Prompt 构建
│   │   │   ├── repository.py                    # Agent / LLM 抽象接口
│   │   │   ├── tool.py                          # BaseTool 与 ToolRegistry
│   │   │   └── tools/
│   │   │       └── knowledge_search_tool.py     # 知识库检索工具
│   │   ├── knowledge/
│   │   └── memory/
│   ├── infrastructure/
│   │   ├── llm/                                 # LiteLLM / 模型客户端
│   │   ├── parser/                              # Git 仓库解析
│   │   └── repository/                          # Redis / pgvector 存储实现
│   ├── trigger/
│   │   └── http/
│   │       ├── chat_controller.py               # Agent 对话、知识库、会话接口
│   │       └── maintenance_controller.py        # 维护接口
│   └── types/
│       ├── request/                             # 请求 DTO
│       └── response.py                          # 统一响应结构
├── scripts/
├── web/
│   └── index.html                               # Web UI
├── main.py                                      # FastAPI 启动入口
├── requirements.txt
└── README.md
```

---

## 快速启动

### 1. 克隆项目

```bash
git clone https://github.com/209044528/Kita-Agent.git
cd Kita-Agent
git checkout develop
```

### 2. 创建 Python 虚拟环境

本项目建议使用 **Python 3.12+**。

Windows：

```bash
py -3.12 -m venv venv
venv\Scripts\activate
```

macOS / Linux：

```bash
python3.12 -m venv venv
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

---

## Docker Compose 启动

### 方式一：完整容器化启动

```bash
docker build -t kita-agent:latest .
docker-compose up -d --build app
docker-compose up -d
```

等待 Ollama 启动后拉取 embedding 模型：

```bash
docker exec -it kita-ollama ollama pull nomic-embed-text
```

可选：拉取本地对话模型。

```bash
docker exec -it kita-ollama ollama pull qwen2.5:3b-instruct
```

检查服务：

```bash
docker-compose ps
curl http://localhost:8000/health
```

访问：

```text
Web UI: http://localhost:8000
API:    http://localhost:8000/api/v1/chat/stream
Docs:   http://localhost:8000/docs
```

---

### 方式二：本地开发模式

先启动依赖服务：

```bash
docker-compose up -d redis db ollama reranker
```

配置 `.env` 后启动后端：

```bash
python main.py
```

---

## 环境变量

在项目根目录新建 `.env` 文件，可参考如下配置：

```env
# LLM
OPENAI_API_KEY=api_key
OLLAMA_BASE_URL=http://localhost:11434

# Redis
REDIS_URL=redis://localhost:6379/0

# PostgreSQL / pgvector
PG_VECTOR_HOST=localhost
PG_VECTOR_PORT=5432
PG_VECTOR_USER=postgres
PG_VECTOR_PASSWORD=postgres
PG_VECTOR_DATABASE=ai-rag-knowledge

# Reranker
RERANKER_API_URL=http://localhost:8080/rerank
```

> 实际变量名称以 `app/core/config.py` 为准。

---

## 日志与维护

### 查看容器日志

```bash
docker-compose logs app --tail=20
```

### 查看实时日志

```bash
docker-compose logs -f app
```

### 数据库导出

```bash
docker exec -i kita-db-pgvector pg_dump -U postgres -d ai-rag-knowledge -f /tmp/knowledge_backup.sql
docker cp kita-db-pgvector:/tmp/knowledge_backup.sql ./knowledge_backup_safe.sql
```

### 数据库导入

```bash
docker cp ./knowledge_backup_safe.sql kita-db-pgvector:/tmp/knowledge_backup.sql

docker exec -i kita-db-pgvector psql -U postgres -d ai-rag-knowledge \
  -c "DROP TABLE IF EXISTS langchain_pg_embedding CASCADE; DROP TABLE IF EXISTS langchain_pg_collection CASCADE;"

docker exec -it kita-db-pgvector psql -U postgres -d ai-rag-knowledge \
  -f /tmp/knowledge_backup.sql
```

### 清理空标签知识

```bash
docker exec -it kita-db-pgvector psql -U postgres -d ai-rag-knowledge \
  -c "DELETE FROM langchain_pg_embedding WHERE cmetadata->>'knowledge_tag' IS NULL;"
```

---

## 工程化升级

### 0. 可靠运行时

运行时现已支持：

- Bearer API Key 认证与用户级会话隔离；
- 同一用户同一会话的 Redis 分布式锁；
- HTTPS Git 白名单、SSRF 防护及仓库大小限制；
- 安全 multipart 文件上传，禁止客户端读取服务器文件路径；
- 模型首包超时、结构化异常、候选模型降级和熔断；
- 异步工具执行、工具超时与取消；
- task ID、跨实例取消标记和结构化 SSE 事件。

生产环境建议配置：

```env
AUTH_ENABLED=true
AUTH_API_KEYS=replace-with-random-key:admin-user:admin
MODEL_FALLBACKS=ollama/qwen2.5:3b-instruct
CORS_ORIGINS=https://your-kita.example.com
```

API 使用：

```http
Authorization: Bearer replace-with-random-key
```

SSE 事件包括 `meta`、`progress`、`tool_start`、`tool_end`、
`content`、`error`、`cancel` 和 `done`。

取消任务：

```text
POST /api/v1/chat/tasks/{task_id}/cancel
```

### 1. 结构化工具调用

工具调用已升级为 JSON Schema 风格：

```json
{
  "tool": "knowledge_search",
  "arguments": {
    "query": "ReAct Agent",
    "tag": "agent-basic"
  }
}
```

`ToolRegistry.definitions()` 可输出通用定义，`openai_tools()` 可输出
Function Calling 定义。旧版正则格式仍作为兼容回退。

---

### 2. MCP Server 接入

现有 `ToolRegistry` 已通过官方 MCP Python SDK 暴露，新增工具后会自动进入 MCP Tool 列表。

```bash
pip install -r requirements-mcp.txt

# stdio
python mcp_server.py

# 独立 Streamable HTTP，默认地址 http://127.0.0.1:8000/
python mcp_server.py --transport streamable-http
```

在 `.env` 中设置 `MCP_ENABLED=true`，还可将 Streamable HTTP 挂载到主服务
`http://localhost:8000/mcp`。

---

### 3. 评测与可观测性

当前已提供：

- Agent 轨迹 JSONL 持久化：`logs/agent_traces.jsonl`；
- 工具调用次数、错误数和平均耗时统计；
- 知识检索在线命中率与离线关键字评测；
- 解析失败、最大步数等 bad case 收集；
- `unittest` 单元测试；
- 指标、轨迹和 RAG 评测 HTTP 接口。

```text
GET  /api/v1/observability/metrics
GET  /api/v1/observability/traces?session_id=...
POST /api/v1/evaluation/rag
```

下一阶段可接入 OTLP Exporter、LangSmith Dataset 和基于语义相关性的评测器。

---

## 项目定位总结

Kita-Agent 是一个用于学习和验证 Agent 工程核心机制的项目。  
它重点展示了：

- 如何手写 ReAct 推理循环；
- 如何设计可扩展工具注册机制；
- 如何将 RAG 检索结果注入 Agent 观察；
- 如何通过 FastAPI 暴露流式 Agent 服务；
- 如何通过 Clean Architecture 降低领域逻辑和基础设施的耦合；
- 如何在工具失败或格式异常时进行纠偏和再规划。

后续可以在此基础上继续扩展为 MCP 工具服务、代码理解 Agent 或具身智能 Agent 原型。
