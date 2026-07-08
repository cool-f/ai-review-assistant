# 📚 期末复习助手

AI 驱动的智能期末复习平台 — 上传课件自动提取知识点，上传作业自动答题并匹配考点，支持基于知识库的 AI 对话辅导、AI 自动出题练习、复习进度追踪。

## ✨ 功能特性

### 📖 课件管理
- 支持上传 **PDF、PPTX、DOCX、TXT、Markdown** 格式课件
- 自动提取文本内容，AI 识别知识点与例题
- 支持**图片型 PDF（扫描件）**多模态 Vision 识别（需 Anthropic/OpenAI/Qwen）
- 上传前 **Token 用量与费用预估**，用户确认后才触发 AI 提取
- 生成 1024 维向量嵌入，支持语义相似度搜索
- 自动发现跨文档知识点关联
- 目录树按课件/作业分类管理

### 📝 作业答疑
- 支持上传多种格式作业，**自动识别题号与题目**
- AI 流式逐题解答（SSE），实时展示解题过程
- 自动将答案与课件知识点关联匹配（jieba 中文分词 + 向量语义匹配）

### 💬 AI 对话辅导
- 基于课件知识库的**上下文感知对话**
- **pgvector 语义检索**：用户问题 → 向量搜索课件相关片段 → 注入对话上下文（替代旧的全量拼接）
- 三级上下文窗口：系统提示 → 语义搜索知识上下文 → 滑动消息窗口
- 支持 Markdown 渲染与 LaTeX 数学公式
- SSE 流式响应，打字机效果
- 多轮对话自动上下文管理

### 📝 AI 自动出题
- 在知识点详情面板一键「出题练习」，AI 根据知识点内容生成练习题
- 支持**选择题、填空题、计算题、证明题**，题型由 AI 自动推断
- 如果课件中有例题，AI 模仿例题格式生成
- 题目**答案默认隐藏**，点击「显示答案」展开
- 右上角「练习」Tab 集中管理所有已生成题目
- 题目持久化存储，支持按课件筛选、引用到聊天追问

### 📊 复习进度追踪
- 每个知识点前显示**状态图标**：🟢已掌握 🟡学习中 ⚪未开始 🔴需加强
- 手动标记「未开始 / 学习中 / 已掌握」
- 做题自动更新状态（连续做对 3 题 → mastered，做错 → struggling）
- 课件节点旁显示「N/M 已掌握」
- 左栏底部**全局进度条**，汇总所有知识点进度

### 📊 用量监控
- 后台看板追踪 AI Token 消耗，支持日预算告警
- 多厂商 API Key 配置，**模型名前缀自动检测提供商**

## 🏗️ 技术栈

| 层级 | 技术 |
|------|------|
| **后端框架** | Python 3.11+ / FastAPI (异步) |
| **数据库** | PostgreSQL 15 + pgvector 向量扩展 |
| **ORM** | SQLAlchemy 2.0 (异步) + Alembic 迁移 |
| **AI 提供商** | DeepSeek / OpenAI / Anthropic / 通义千问 (DashScope) — **自动检测** |
| **向量嵌入** | DashScope text-embedding-v4 (1024 维) + IVFFlat 索引 |
| **中文分词** | jieba |
| **Token 计数** | tiktoken |
| **文件解析** | PyMuPDF / python-pptx / python-docx |
| **前端框架** | React 18 + TypeScript (strict) |
| **构建工具** | Vite 5 |
| **样式** | Tailwind CSS 3 |
| **Markdown** | react-markdown + KaTeX (LaTeX 数学公式) |
| **HTTP 客户端** | Axios + SSE (fetch ReadableStream) |

## 📁 项目结构

```
review_assistant/
├── backend/                       # Python FastAPI 后端
│   ├── main.py                    # 应用入口, 生命周期, CORS, 路由注册
│   ├── config.py                  # pydantic-settings 配置管理
│   ├── database.py                # 异步 SQLAlchemy 引擎与会话
│   ├── models.py                  # 15 张 ORM 数据模型
│   ├── api/                       # REST API 路由
│   │   ├── chat.py                # 对话会话 & SSE 消息流
│   │   ├── coursewares.py         # 课件 CRUD + 上传 + preflight
│   │   ├── knowledge_points.py    # 知识点提取 & 列表
│   │   ├── examples.py            # 例题列表
│   │   ├── homeworks.py           # 作业 CRUD + AI 答题
│   │   ├── questions.py           # AI 自动出题 (SSE 流式)
│   │   ├── progress.py            # 复习进度追踪
│   │   ├── links.py               # 知识点关联
│   │   ├── folders.py             # 文件夹管理
│   │   └── admin.py               # Token 用量看板
│   ├── services/                  # 业务逻辑
│   │   ├── ai_client.py           # AI 客户端抽象工厂 + 自动检测
│   │   ├── ai_extractor.py        # AI 知识点提取
│   │   ├── text_extractor.py      # 文件文本提取 + Vision 识别
│   │   ├── chat_service.py        # RAG 语义搜索对话引擎
│   │   ├── homework_service.py    # 作业识别 + 并发解题
│   │   ├── question_service.py    # AI 自动出题服务
│   │   ├── embedding_service.py   # DashScope 向量嵌入
│   │   ├── linking_service.py     # pgvector 相似度关联
│   │   ├── kp_matcher.py          # jieba 关键词匹配
│   │   ├── token_counter.py       # Token 日志 & 预算
│   │   └── providers/             # AI 提供商适配
│   │       ├── anthropic.py       # Anthropic (Claude) + Vision
│   │       ├── openai.py          # OpenAI (GPT)
│   │       ├── qwen.py            # 通义千问 (DashScope)
│   │       └── deepseek.py        # DeepSeek
│   ├── schemas/                   # Pydantic 请求/响应模型
│   └── alembic/                   # 数据库迁移脚本
├── frontend/                      # React + TypeScript 前端
│   ├── vite.config.ts             # Vite 配置 (代理 /api → :8000)
│   ├── tsconfig.json              # TypeScript strict 配置
│   ├── tailwind.config.js         # Tailwind CSS 配置
│   └── src/
│       ├── main.tsx               # React 入口
│       ├── App.tsx                 # 根布局 (顶部 Tab 切换)
│       ├── api/                   # API 客户端
│       │   ├── client.ts          # Axios 实例 + 拦截器
│       │   └── chat.ts            # 对话 API
│       ├── types/                 # TypeScript 类型定义
│       ├── hooks/
│       │   └── useSSE.ts          # SSE Hook (自动重连, 指数退避)
│       ├── lib/
│       │   └── markdown.ts        # Markdown 渲染插件
│       └── components/            # React 组件
│           ├── DirectoryTree.tsx  # 左侧: 文件上传 & 目录树
│           ├── FolderTree.tsx     # 文件夹树形视图
│           ├── ChatPanel.tsx      # 对话面板
│           ├── PracticePanel.tsx  # 练习面板 (按课件分组题目)
│           ├── MessageBubble.tsx  # 消息气泡
│           ├── StreamingMessage.tsx # 流式消息 (打字机效果)
│           ├── DetailPanel.tsx    # 右侧: 知识点/题目/作业详情
│           ├── ConfirmModal.tsx   # 确认对话框
│           └── CollapseToggle.tsx # 侧栏折叠按钮
├── docker-compose.yml             # PostgreSQL 15 + pgvector
├── .env.example                   # 环境变量模板
└── data/                          # 数据库持久化存储
```

## 🚀 快速开始

### 前置要求

- **Python** 3.11+
- **Node.js** 18+ / pnpm (或 npm)
- **Docker** & Docker Compose

### 1. 克隆项目

```bash
git clone <repo-url>
cd review_assistant
```

### 2. 配置环境变量

在项目根目录下，复制环境变量模板并填入你的 API Key：

```bash
cp .env.example .env
```

编辑 `.env`，必须填写以下两项：

```env
# AI 提供商 (自动检测: 根据模型名前缀推断, 也可手动指定)
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxxxxxxx

# 向量嵌入 (通义千问 DashScope)
DASHSCOPE_API_KEY=sk-xxxxxxxx
```

> **注意**：`AI_PROVIDER` 可留空，系统会根据 `AI_DEFAULT_MODEL` 的前缀自动检测（如 `gpt-` → OpenAI, `claude` → Anthropic, `deepseek` → DeepSeek, `qwen` → 通义千问）。图片型 PDF（扫描件）识别需要 Vision 能力，需使用 `anthropic`、`openai` 或 `qwen`。

### 3. 启动数据库

```bash
docker-compose up -d
```

这会启动一个 PostgreSQL 15 容器（带 pgvector 扩展），默认端口 `5432`。

### 4. 安装后端依赖

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 5. 运行数据库迁移

```bash
# 在 backend/ 目录下执行（alembic.ini 所在目录）
alembic upgrade head
```

### 6. 启动后端

```bash
# 回到项目根目录，因为代码使用 backend.xxx 绝对导入
cd ..
uvicorn backend.main:app --reload --port 8000
```

### 7. 安装前端依赖 & 启动

```bash
cd frontend
npm install
npm run dev    # 启动 Vite 开发服务器 (端口 5173)
```

### 8. 打开应用

浏览器访问 **http://localhost:5173**

## 🎯 使用指南

### 上传课件
1. 点击左上角「上传」按钮（确认当前处于「课件」模式）
2. 选择课件文件（支持 PDF/PPTX/DOCX/TXT/MD）
3. 系统预估 Token 用量与费用 → 用户确认 → 开始处理
4. AI 自动提取知识点、例题 → 生成向量嵌入 → 建立跨课件关联
5. 在左侧目录树可浏览课件及其知识点（带进度状态图标）

### 上传作业
1. 在左栏顶部切换到「作业」模式
2. 上传作业文件
3. AI 自动识别题目并流式解答
4. 答案自动关联到课件的相关知识点

### AI 对话
1. 在顶部选择「对话」Tab
2. 选中一个课件，新建对话会话
3. 输入问题，AI **语义搜索**课件相关知识后回答
4. 右侧面板可查看当前课件知识点详情
5. 支持引用知识点到对话中

### AI 出题练习
1. 在知识点详情面板点击「AI 出题练习」按钮
2. AI 自动生成练习题（题型根据知识点自动推断）
3. 在顶部切换到「练习」Tab 集中管理所有题目
4. 题目**答案默认隐藏**，点击「显示答案」展开
5. 可「引用到聊天」追问 AI

### 复习进度追踪
- 知识点前显示状态图标：🟢已掌握 🟡学习中 ⚪未开始 🔴需加强
- 右侧面板点击「未开始/学习中/已掌握」手动标记
- 做 AI 练习题自动更新掌握状态
- 左栏底部全局进度条汇总进度

## ⚙️ 配置说明

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `AI_PROVIDER` | AI 提供商: `anthropic` / `openai` / `qwen` / `deepseek` | `deepseek` |
| `AI_DEFAULT_MODEL` | 默认模型 ID（可留空自动检测） | `deepseek-chat` |
| `AI_MAX_TOKENS` | 每次请求最大 Token 数 | `4096` |
| `AI_TEMPERATURE` | 生成温度 (0–1) | `0.7` |
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API Key (向量嵌入) | — |
| `POSTGRES_HOST` | PostgreSQL 主机地址 | `localhost` |
| `POSTGRES_PORT` | PostgreSQL 端口 | `5432` |
| `POSTGRES_USER` | 数据库用户名 | `review_user` |
| `POSTGRES_PASSWORD` | 数据库密码 | `review_pass` |
| `POSTGRES_DB` | 数据库名称 | `review_db` |
| `CORS_ORIGINS` | 前端跨域来源 | `http://localhost:5173` |
| `DEBUG` | 调试模式 | `true` |

## 🧠 架构设计

### AI 提供商抽象与自动检测

通过 `AbstractAIClient` 抽象基类统一不同 AI 提供商的调用接口，支持**模型名前缀自动检测**：

```
AbstractAIClient
├── AnthropicClient  (原生 Anthropic SDK, 支持 Vision)
├── OpenAIClient     (OpenAI 兼容 SDK, 支持 Vision)
├── DeepSeekClient   (OpenAI 兼容)
└── QwenClient       (DashScope OpenAI 兼容, 支持 Vision)
```

自动检测规则：`claude-` → Anthropic, `gpt-` → OpenAI, `deepseek-` → DeepSeek, `qwen-` → 通义千问。

### 知识点提取流水线

```
文字型 PDF: 上传 → 文本提取 (PyMuPDF) → AI 知识点提取 → 向量嵌入 → 跨文档关联
图片型 PDF: 上传 → 多模态 Vision 逐页识别 → 片段去重合并 → 向量嵌入 → 跨文档关联
```

### 语义搜索对话（RAG）

```
用户问题 → query embedding → pgvector <=> 相似度搜索
  → chunks + knowledge_points top-K
  → 注入对话上下文 → AI 回答
```

### AI 自动出题

```
知识点 → 收集知识点内容 + 例题 + 课件片段
  → AI 生成题目 (JSON 数组) → 持久化 → 练习面板展示
```

### 复习进度状态机

```
手动标记: 直接覆盖 status (权重最高)
做题提交:
  - 有手动标记 → 不自动覆盖
  - 做错 → struggling
  - 做对 ≥3 次 → mastered
  - 做对 ≥1 次 → in_progress
  - 未答题 → not_started
```

### SSE 流式架构

前端使用 `fetch` + `ReadableStream` 实现 SSE 监听，支持：
- 超时检测 (120s)
- 指数退避自动重连 (最多 3 次)
- AbortController 中断
- 统一 SSE 事件格式: `data: {json}\n\n`

## 📄 License

MIT
