

# Kita-Agent 

本项目旨在通过手写核心逻辑，深入理解大语言模型（LLM）驱动的智能体“感知-思考-行动”循环。

## 📂 项目结构

本项目采用整洁架构（Clean Architecture）进行模块划分，核心业务逻辑与外部依赖相互解耦，确保系统的高可维护性与可扩展性。
```text
Kita-Agent-develop/
├── app/                            # 后端核心应用程序目录
│   ├── application/                # 应用层：负责编排领域模型，处理具体业务用例
│   │   └── services/               # 应用服务
│   ├── core/                       # 核心配置层：存放全局配置和系统级跨层组件
│   │   └── config.py               # 项目环境与参数配置
│   ├── domain/                     # 领域层：纯粹的业务逻辑与实体，不依赖外部框架
│   │   ├── agent/                  # 智能体领域：包含 entity.py, prompt.py (提示词逻辑), repository.py (接口定义)
│   │   └── memory/                 # 记忆领域：包含 entity.py 记忆实体定义
│   ├── infrastructure/             # 基础设施层：具体技术细节与外部系统接入
│   │   ├── llm/                    # 大语言模型服务接入
│   │   └── repository/             # 数据存储实现
│   ├── trigger/                    # 触发层（接口层）：负责接收外部请求并路由到应用层
│   │   └── http/                   # HTTP 控制器
│   └── types/                      # 类型定义层：数据传输对象 (DTO) 及协议定义
│       ├── request/                # 请求参数校验模型
│       └── response.py             # 统一响应格式模型
├── web/                            # 前端静态资源与页面
│   └── index.html                  # Web 交互入口
├── main.py                         # 应用程序启动入口
└── requirements.txt                # 环境依赖清单
```

## 🚀 环境准备

### 1. 克隆与进入项目
```bash
git clone https://github.com/209044528/Kita-Agent.git
cd Kita-Agent
```

### 2. 创建并激活虚拟环境
本项目强制要求使用 **Python 3.12+**。

```bash
py -3.12 -m venv venv
venv\Scripts\activate
```

### 3. 安装依赖
```bash
pip install -r requirements.txt
```

### 4. 配置环境变量
在项目根目录新建 `.env` 文件，并填写 API Key：
```env
OPENAI_API_KEY="Key"
```

## 🛠️ 快速启动

运行以下命令启动 Kita-Agent：
```bash
python main.py
```

## 环境导出

```
pip freeze > requirements.txt
```