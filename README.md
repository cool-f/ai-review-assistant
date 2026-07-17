# 期末复习助手

一个面向个人复习场景的本地 AI 学习工作区。项目以“课程”为业务边界，把课件摄取、知识点校正、课程问答、作业解答、练习判分和掌握度更新串成可恢复、可核验的学习闭环。

> 当前版本是单用户、单端应用，不包含注册登录、权限、多租户，也不拆分学生端和教师端。请仅部署在可信网络环境中。

## 核心能力

- **课程隔离**：课件、作业、会话、练习、进度和用量均按当前课程过滤。
- **课件摄取**：上传前预检，分别跟踪解析、知识提取、向量化和关联发现状态。
- **可恢复任务**：课件摄取、作业解答和聊天支持失败重试、服务重启恢复或事件回放。
- **可信问答**：回答附带课件、页码和内容摘要；同一请求通过幂等键避免重复调用模型。
- **作业解答**：逐题流式生成，页面断开后后台继续执行，部分失败只重试未完成题目。
- **练习闭环**：支持提交答案、自动或 AI 判分、作答历史以及掌握度自动更新。
- **知识校正**：知识点可人工编辑，修改后重建向量并刷新同课程内的跨课件关联。
- **用量与预算**：统一记录文本生成和嵌入调用，可按课程、用途和提供商查看并限制每日预算。

业务主流程：

```text
创建课程
  → 上传并摄取课件
  → 校正知识点并重建语义索引
  → 课程问答 / 作业解答 / 生成练习
  → 提交答案并获得反馈
  → 自动更新或人工覆盖掌握度
```

## 技术栈

| 层级 | 技术 |
| --- | --- |
| Web | React 18、TypeScript、Vite 8、Tailwind CSS、Vitest |
| API | FastAPI、Pydantic 2、SQLAlchemy 2、Alembic、Pytest |
| 数据库 | PostgreSQL 15、pgvector |
| AI | DeepSeek、OpenAI、Anthropic、通义千问；DashScope Embedding |
| 工程 | npm workspaces、uv、Docker Compose |

## 项目结构

```text
review_assistant/
├─ apps/
│  ├─ api/
│  │  ├─ alembic/                         # 001—010 数据库迁移
│  │  ├─ src/review_assistant/
│  │  │  ├─ domain/                       # 无 I/O 的领域规则
│  │  │  ├─ application/                  # 业务用例与后台任务
│  │  │  ├─ infrastructure/               # 数据库、AI、文档与用量适配器
│  │  │  └─ interfaces/http/              # FastAPI 路由与接口模型
│  │  └─ tests/                           # 领域、应用、迁移和 HTTP 契约测试
│  └─ web/
│     └─ src/
│        ├─ app/                           # 应用装配与课程上下文
│        ├─ features/                      # chat/library/practice/study/usage
│        └─ shared/                        # API、SSE、类型、Markdown 和通用 UI
├─ docs/
│  ├─ architecture/                       # 架构决策记录
│  └─ specs/                              # 业务验收规格
├─ CONTEXT.md                             # 领域术语与核心约束
├─ docker-compose.yml                     # PostgreSQL + pgvector
└─ package.json                           # 根目录开发、测试和构建命令
```

旧的 `frontend/`、`backend/`、空占位包和代理工具工作流均不保留。

## 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20.19+ 或 22.12+
- Docker Desktop 或兼容的 Docker Engine
- 至少一个文本生成模型 API Key
- 使用向量化和语义检索时需要 DashScope API Key

## 快速启动

以下命令以 PowerShell 和项目根目录为例。

### 1. 配置环境变量

```powershell
Copy-Item .env.example .env
```

建议显式配置文本生成厂商。以 DeepSeek 为例：

```env
AI_PROVIDER=deepseek
AI_DEFAULT_MODEL=deepseek-chat
DEEPSEEK_API_KEY=your-key

EMBEDDING_PROVIDER=dashscope
EMBEDDING_MODEL=text-embedding-v4
DASHSCOPE_API_KEY=your-key
```

如果 `AI_PROVIDER` 和 `AI_DEFAULT_MODEL` 留空，后端会根据已配置的 API Key 自动选择厂商。`.env` 包含密钥，已被 Git 忽略，不要提交。

### 2. 安装依赖

```powershell
uv sync --project apps/api --extra dev
npm install
```

### 3. 启动数据库并迁移

```powershell
docker compose up -d db
npm run db:upgrade
npm run db:status
```

迁移状态应显示：

```text
010 (head)
```

### 4. 启动 API

新开一个终端：

```powershell
npm run dev:api
```

### 5. 启动 Web

再开一个终端：

```powershell
npm run dev:web
```

启动后可访问：

- Web：<http://localhost:5173>
- API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/health>

## 推荐验收路径

1. 创建课程。
2. 上传课件并确认预检信息。
3. 等待解析、知识提取、向量化和关联发现进入终态。
4. 查看并编辑知识点，确认索引能够重建。
5. 发起课程问答，检查来源课件和页码。
6. 上传作业并启动解答，刷新页面验证后台任务和事件回放。
7. 生成练习、提交答案，检查判分、历史和掌握度变化。
8. 查看用量面板及每日预算。

## 常用命令

```powershell
# 数据库
npm run db:upgrade
npm run db:status

# 开发
npm run dev:api
npm run dev:web

# 质量检查
npm run test:api
npm run test:web
npm run typecheck:web
npm run build:web
npm run check
npm audit
```

## 状态与恢复语义

课件摄取分别记录 `parse_status`、`knowledge_status`、`embedding_status` 和 `linking_status`，对外汇总状态为 `processing / completed / partial / failed`。向量化失败不会伪装成完全成功，已解析内容仍可浏览。

作业状态为 `ready / processing / completed / partial / failed`。`partial` 表示已有可用答案，但仍有题目可以继续重试。

服务启动时会恢复未完成的课件任务，并把中断的作业解答调整为可继续状态。聊天和作业的流式连接断开不会重复创建任务。

## 本地数据

- PostgreSQL 数据默认保存在 `data/pgdata/`。
- 上传文件默认保存在 `uploads/`。
- `.env`、数据库、上传文件、虚拟环境、依赖、测试缓存和构建产物均已被 Git 忽略。
- `docker compose down` 只停止并移除容器；不要随意添加 `-v` 或手动删除 `data/pgdata/`，否则可能丢失本地数据。

## 常见问题

### `/api/courses` 返回 500

先检查数据库迁移：

```powershell
npm run db:status
npm run db:upgrade
```

确认最终版本是 `010 (head)`，然后刷新页面。

### AI 问答可用，但语义检索或向量化失败

文本问答和向量化使用不同服务。除文本生成厂商的 Key 外，还需要配置：

```env
DASHSCOPE_API_KEY=your-key
```

### 修改 `.env` 后没有生效

配置会在 API 进程启动时加载。保存 `.env` 后请重启 API；如果使用 Windows 用户或系统环境变量，也需要重新打开终端后再启动。

## 文档

- [业务验收规格](docs/specs/business-closure-refactor.md)
- [领域上下文与术语](CONTEXT.md)
- [ADR-001：单仓应用布局与深模块边界](docs/architecture/ADR-001-monorepo-and-deep-modules.md)
