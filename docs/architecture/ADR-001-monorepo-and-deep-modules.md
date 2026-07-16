# ADR-001：单仓库布局与深模块边界

## 状态

已接受。

## 决策

根目录不再以 `backend/`、`frontend/` 两个大桶组织代码，而采用可部署应用、共享契约和文档分区：

```text
apps/
  api/
    alembic/                 # PostgreSQL 迁移
    src/review_assistant/
      domain/                # 无 I/O 的领域规则
      application/           # 业务用例与任务编排
      infrastructure/        # 数据库、AI、文档和计量适配器
      interfaces/http/       # FastAPI 路由与请求/响应模型
    tests/
  web/
    src/app/                 # 单端应用装配和课程上下文
    src/features/            # library/chat/practice/study/usage
    src/shared/              # API、SSE、类型和通用 UI
packages/
  contracts/                 # 跨端接口与 SSE 事件契约说明
docs/
  specs/
  architecture/
```

## 关键边界

1. **课程聚合边界**：课件、作业、会话、练习、进度和用量均以当前课程过滤，跨课程读取必须显式拒绝。
2. **任务执行端口**：HTTP 只校验请求并启动任务；`application/ingestion/pipeline.py`、作业服务和聊天任务负责状态、幂等、恢复及外部调用。
3. **练习提交端口**：调用者只提交题目和答案；判分、作答记录和进度更新封装在同一事务中。
4. **AI 与计量端口**：文本生成和嵌入调用统一经过预算检查及用量记录，业务服务不直接绕过计量适配器。
5. **前端业务特性边界**：页面按业务能力组织；共享网络、流式处理和基础 UI 不反向依赖具体特性。

## 后果

- 摄入、聊天、作业和练习规则集中在应用层，路由只承担传输职责。
- 外部 AI、数据库和文件系统通过适配器隔离，测试可以替换边界实现。
- 不保留 `backend/`、`frontend/` 兼容目录或 Claude 多代理工作流。
- 本项目保持单用户、单端；登录、权限、学生端和教师端不属于本次边界。
