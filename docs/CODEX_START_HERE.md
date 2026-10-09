# Codex — start here

1. Read [`v2/00_SOURCE_OF_TRUTH.docx`](v2/00_SOURCE_OF_TRUTH.docx) and [`v2/01_FEATURE_REGISTRY_80.docx`](v2/01_FEATURE_REGISTRY_80.docx) — plus [`FEATURE_REGISTRY_ADDENDUM.md`](FEATURE_REGISTRY_ADDENDUM.md) for the owner's later additions (F-081+).
2. Read engineering docs [`01_ARCHITECTURE_STACK.docx`](01_ARCHITECTURE_STACK.docx) through [`07_TESTING_QUALITY_GATES.docx`](07_TESTING_QUALITY_GATES.docx).
3. Read [`AI_ENGINEERING_CONSTITUTION.md`](AI_ENGINEERING_CONSTITUTION.md) — the standing Codex/Claude instruction for this repo.
4. Load `codex_tasks.json` as the original dependency registry, **not** as completion state.
   Before choosing work, reconcile it with [`IMPLEMENTED.md`](IMPLEMENTED.md),
   [`IN_PROGRESS.md`](IN_PROGRESS.md), Git ancestry, and the current code/tests.
5. For UI/competitor work, read the maintained matrix
   [`COMPETITOR_UI_ANALYSIS.md`](COMPETITOR_UI_ANALYSIS.md) and the accepted design documents
   under [`design/`](design/) before proposing a duplicate feature.
6. Start from the earliest genuinely open dependency, not automatically from T-001.
7. Every PR title: `[T-xxx][F-xxx] short description`.
8. Never silently remove/de-scope a Feature ID.
9. Preserve immutable source assets and version lineage.
10. AI must emit validated OperationPlan; do not execute arbitrary model-generated code.
