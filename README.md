

# Kita-Agent 

本项目旨在通过手写核心逻辑，深入理解大语言模型（LLM）驱动的智能体“感知-思考-行动”循环。

## 📂 项目结构

目前 Kita-Agent 的物理骨架如下：

```text
Kita-Agent/
├── core/                  # Agent 核心逻辑大脑
│   ├── llm_api.py         # 大模型 API 调用封装
│   ├── prompt.py          # 系统人设与提示词模板管理
│   ├── memory.py          # 记忆模块
│   └── tools.py           # 外部工具集
├── ui/                    # 用户界面交互层
│   └── chat_window.py     # 聊天视窗
├── .env                   # 环境变量
├── .gitignore             # Git 忽略文件清单
├── requirements.txt       # 项目依赖包列表
├── README.md              # 项目使用说明文档
└── main.py                # 程序的执行入口
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