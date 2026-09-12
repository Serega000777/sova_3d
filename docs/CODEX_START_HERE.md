# Codex — start here

1. Read [`v2/00_SOURCE_OF_TRUTH.docx`](v2/00_SOURCE_OF_TRUTH.docx) and [`v2/01_FEATURE_REGISTRY_80.docx`](v2/01_FEATURE_REGISTRY_80.docx).
2. Read engineering docs [`01_ARCHITECTURE_STACK.docx`](01_ARCHITECTURE_STACK.docx) through [`07_TESTING_QUALITY_GATES.docx`](07_TESTING_QUALITY_GATES.docx).
3. Read [`AI_ENGINEERING_CONSTITUTION.md`](AI_ENGINEERING_CONSTITUTION.md) — the standing Codex/Claude instruction for this repo.
4. Load `codex_tasks.json`. Start at T-001 and obey dependencies.
5. Every PR title: `[T-xxx][F-xxx] short description`.
6. Never silently remove/de-scope a Feature ID.
7. Preserve immutable source assets and version lineage.
8. AI must emit validated OperationPlan; do not execute arbitrary model-generated code.
