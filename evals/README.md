# Archer workflow evals

这组离线 Evals 固定 intent、tool selection、核心 prompt/context assembly 与 Hugo 副作用策略的生产输出。
不调用真实模型，不访问网络，不执行工具副作用，也不读取用户学习路由。

```bash
.venv/bin/python evals/run_workflow_evals.py
```

只有在 Prompt、意图规则或路由契约经过人工确认后，才允许更新 baseline：

```bash
.venv/bin/python evals/run_workflow_evals.py --update-baseline
git diff -- evals/workflow_baseline.json
```

更新时必须审查每个 case 的语义变化。Hugo 契约额外要求：能力询问、内容点评和否定发布不得进入副作用流程；发布与删除必须标记 `approval_required`。
