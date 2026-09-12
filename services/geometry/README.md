# services/geometry

Deterministic CAD kernel service (C++20, CMake). Executes validated
OperationPlans; the LLM never touches geometry directly.

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
```

No local toolchain? `docker build -t physical-ai-geometry .` builds and runs
the tests inside the image. Configure with `-DPHYSICAL_AI_WITH_OCCT=ON` once
Open CASCADE 8 is available (T-022/T-033).
