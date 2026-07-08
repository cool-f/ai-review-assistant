# 多 Agent 协作开发工作流 — 主对话层编排

## 流程

```
用户提出需求
  → 主对话层搜索项目文件，组装上下文包
  → Agent 1 (Planner) 输出结构化规格书
  → 暂停展示给用户确认
  → 用户确认后
  → Agent 2 (Engineer) 实现代码
  → Agent 3 (Reviewer) 审查代码
  → [revise] → Engineer 修改 → Reviewer 再审（最多3轮）
  → [pass] → Planner 最终验收
  → ✅ 完成
```

## 循环控制

1. 最大迭代：Engineer ↔ Reviewer 最多 3 轮
2. 通过即停：Reviewer pass → Planner 验收
3. 改进停滞：连续两轮阻塞项未减少 → 终止，拆分任务

## 上下文包结构

每个 Agent spawn 时携带：
```json
{
  "project_structure": "<tree 输出>",
  "design_doc_summary": "<相关章节摘要>",
  "related_files": [{"path": "...", "content": "..."}],
  "previous_stage_output": {}
}
```

## 任务粒度

每个任务不超过 5 个文件改动。大需求拆分为多个 task_id。
