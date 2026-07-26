# ARIS Agent Rules

## Protocol First

- When ARIS behavior depends on AI intent, use an explicit machine-readable protocol instead of semantic keyword heuristics.
- Define the protocol in schema first, then parse and handle it in code. Current examples:
  - structured response field `task_mode`
  - structured message field `data_payload.submission_draft`
- Do not infer workflow topology from domain phrases such as `EOS`, `状态方程`, `缩放比例`, or `parameter sweep` when an explicit protocol field can carry that meaning.

## Workflow Topology

- Use `task_mode="single"` for one runnable submission preview.
- Use `task_mode="batch"` for multi-structure, parameter-grid, or high-throughput preparation.
- Use `task_mode="none"` for analysis-only or non-submission turns.
- If a new UI or backend branch needs AI classification, add a new explicit field and a tested handler instead of adding phrase lists.

## Change Discipline

- For new AI-visible protocols, update prompt/specification, parser/handler, and regression tests together.
- If you are about to add business-specific keyword matching to recover AI intent, stop and replace it with an explicit structured field unless there is a documented blocker.
