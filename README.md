# 期末复习助手

一个本地部署、单用户、单端的 AI 复习工作区。它以“课程”为业务边界，把课件摄取、知识点校正、课程问答、作业解答、练习判定和掌握度更新串成可恢复、可核验的学习闭环。

本版本明确不包含用户注册/登录、权限、多租户，也不拆分学生端和教师端。请仅在可信的本地网络环境中使用。

## 业务闭环

```text
创建课程
  → 上传并摄取课件
  → 校正知识点并重建语义索引
  → 课程问答 / 作业解答 / 生成练习
  → 提交练习答案并获得反馈
  → 自动更新或人工覆盖掌握度
```

核心行为：

- 课程是课件、作业、会话、练习和进度的聚合边界；当前页面的数据均按所选课程过滤。
- 课件上传前会预检文件、读取方式和预计用量；解析、知识提取、向量化、关联发现分别记录状态。
- 向量化失败时课件仍可浏览，但会明确标记“语义能力降级”；中断任务可在服务重启后恢复。
- 作业先上传为“待解答”，用户再启动流式逐题求解；求解由独立后台任务执行，页面断开后仍会继续，重连可回放进度，失败后只继续未完成题目。
- 练习必须提交答案。选择/填空题使用确定性判定，计算/证明题使用可替换 AI 判分适配器。
- 同一题可保留多次作答历史，但只首次计入掌握度；连续答对 3 道不同题自动掌握，最新答错转为需加强。
- 人工进度状态覆盖自动结果，也可清除覆盖恢复自动判断。
- 课程问答保存课件、页码和摘要引用；知识点编辑后会重建向量并刷新同课程内的跨课件关联。
- 所有文本生成和嵌入调用统一执行预算检查并按课程、业务用途、提供商记录用量。
- 聊天请求使用幂等键；网络重连最多 3 次，同一请求不会重复保存消息或重复调用模型。

## 状态语义

课件摄取不会再用一个模糊的 `completed` 覆盖全部阶段：

| 阶段 | 字段 | 典型状态 |
| --- | --- | --- |
| 文件解析 | `parse_status` | pending / processing / completed / failed |
| 知识提取 | `knowledge_status` | pending / processing / completed / failed |
| 向量化 | `embedding_status` | pending / processing / completed / failed |
| 关联发现 | `linking_status` | pending / processing / completed / failed |
| 对外汇总 | `status` | processing / completed / partial / failed |

作业状态使用 `ready / processing / completed / partial / failed`；`partial` 表示已有可用答案，但仍有题目待重试。

## 工程结构

```text
apps/
  api/
    alembic/                 # 001—010 数据库迁移
    src/review_assistant/
      domain/                # 无 I/O 的课程、进度、预算、幂等规则
      application/           # 摄取、作业、练习、知识、聊天用例
      infrastructure/        # PostgreSQL、AI、文档、用量适配器
      interfaces/http/       # FastAPI 路由与请求/响应模型
    tests/                   # 领域、应用和 HTTP 契约测试
  web/
    src/app/                 # 单端应用装配
    src/features/            # chat/library/practice/study/usage
    src/shared/              # API、SSE、Markdown、类型和通用 UI
packages/contracts/          # 跨端接口与事件契约说明
docs/
  architecture/             # 架构决策
  specs/                    # 本次业务闭环验收规格
CONTEXT.md                   # 领域术语和不可破坏约束
```

根目录不再保留旧的 `frontend/`、`backend/` 和 Claude 多代理工作流。

## 环境要求

- Python 3.11+
- Node.js 20.19+ 或 22.12+
- Docker（用于 PostgreSQL 15 + pgvector）
- 至少一个文本生成模型 API Key
- 使用语义检索时需要 DashScope API Key

## 本地启动

1. 准备配置：

```powershell
Copy-Item .env.example .env
```

填写 `.env` 中实际使用的 API Key。不要提交 `.env`。

2. 安装依赖：

```powershell
python -m pip install -e "apps/api[dev]"
npm install
```

3. 启动数据库并迁移：

```powershell
docker compose up -d db
Set-Location apps/api
python -m alembic upgrade head
Set-Location ../..
```

4. 启动 API：

```powershell
python -m uvicorn review_assistant.main:app --app-dir apps/api/src --reload --host 0.0.0.0 --port 8000
```

5. 在另一个终端启动 Web：

```powershell
npm run dev:web
```

访问 `http://localhost:5173`。API 文档位于 `http://localhost:8000/docs`，健康检查位于 `http://localhost:8000/api/health`。

## 数据库升级

已有旧数据库必须依次执行到迁移 `010`。迁移 `007` 会建立默认课程并回填旧数据；后续迁移增加作答记录、知识修订/引用、用量维度和聊天幂等请求。

```powershell
Set-Location apps/api
python -m alembic current
python -m alembic upgrade head
```

只校验迁移 SQL、不连接数据库：

```powershell
python -m alembic upgrade head --sql
```

## 质量检查

```powershell
npm run test:api
npm run test:web
npm run typecheck:web
npm run build:web
npm audit
```

也可以一次执行：

```powershell
npm run check
```

## 数据与恢复

- PostgreSQL 数据默认位于 `data/pgdata/`，上传文件默认位于 `uploads/`；两者均被 Git 忽略。
- 删除课程前必须先清空其课件、作业、文件夹和会话，服务端会拒绝误删非空课程。
- 服务启动时会重新排队未完成的课件摄取，并将被中断的作业求解标记为可继续的 `partial`。
- 达到 `DAILY_TOKEN_BUDGET` 后，新 AI/嵌入调用返回明确的预算错误；已有资料、答案、历史和进度仍可读取。

## 业务与架构文档

- [业务验收规格](docs/specs/business-closure-refactor.md)
- [领域上下文与术语](CONTEXT.md)
- [ADR-001：单仓应用布局与深模块缝隙](docs/architecture/ADR-001-monorepo-and-deep-modules.md)
