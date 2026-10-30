# Sova 3D: gap analysis по AI-сервисам генерации 3D

Дата сверки: 2026-10-30. Базовый документ: пользовательский анализ Meshy, Tripo,
Hi3D, YVO3D и Hunyuan3D (SHA-256
`1ce5272ffd5e7f9efa708c5ce3c8b23a7250ec97d9e8c57c80e19960cd6184d2`).

## Принцип заимствования

Sova не копирует названия провайдеров и маркетинговые обещания. Полезные паттерны
переносятся как независимые продуктовые цели: preview до дорогого шага, явная цена,
варианты без перезаписи, проверка экспортируемого файла, разные presets для game/print/
character и возможность заменить движок без изменения клиента. «Game-ready»,
«print-ready» и «точная копия» показываются только при наличии проверяемого артефакта.

## Что уже сильнее или не хуже базовых паттернов

- Durable async jobs с progress, idempotency, retry, pause/resume/cancel и DB state machine:
  `app/models/execution.py`, `app/services/jobs.py`, `app/jobs/runner.py`.
- Content-addressed S3/MinIO storage и короткоживущие signed URLs: `app/storage.py`.
- Immutable project versions, provenance и история: `app/models/versioning.py`.
- Реальные text-to-mesh и single-photo-to-mesh через sandboxed Shap-E:
  `worker/generate_mesh.py`, `worker/reconstruction.py`.
- Независимый scan-provider Protocol уже существует, но покрывает reconstruction, а не весь
  lifecycle генерации: `worker/reconstruction.py::Reconstructor`.
- Mesh diagnostics/repair, print gate, STL/3MF, game LOD/UV/collider, split/connectors,
  build-plate layout, scenes и marketplace уже являются реальными worker/API путями.
- Клиенты показывают wireframe/topology, game triangle budget, print analysis и immutable
  version history, а не только красивый preview.

## Матрица разделов 11–16

Статусы рассчитаны только по 30 строкам P0–P3 из исходного backlog:
**16 implemented and verified, 8 partial, 5 missing, 1 externally blocked**.

| Приоритет | Возможность | Статус | Доказательство / точная граница |
|---|---|---|---|
| P0 | Single image-to-3D | implemented and verified | Provider-neutral image asset → sandboxed Shap-E → repair → source lineage → normalized STL/GLB; скрытые поверхности явно помечены как inferred. |
| P0 | Multi-view 4 ракурса | implemented and verified | Отдельный default-off `colmap` route принимает 4–8 JPEG/PNG одного предмета, требует минимум четыре камеры в единой COLMAP-связности, масштабирует по `size_mm`, проецирует исходные фото в GLB и сохраняет все source assets. Ориентация честно помечена как principal-axes/unmeasured. |
| P0 | Нормализованный GLB | implemented and verified | Text/image Shap-E generation автоматически конвертирует repaired STL в GLB, прогоняет integrity report и сохраняет raw STL отдельно от normalized asset. |
| P0 | Viewer + wireframe | implemented and verified | Web/mobile viewer, topology overlay, material/topology inspection. |
| P0 | Provider abstraction | implemented and verified | Единые `ThreeDProvider`, capabilities/estimate/prepare, Router v1 и durable provider/model/version attribution используются Shap-E и отдельным COLMAP adapter без изменения клиентского request contract. |
| P0 | Async queue + progress | implemented and verified | Durable `Job`, worker claim loop, progress, retry, pause/resume/cancel. |
| P0 | Стоимость до запуска | partial | Общий credit pricing есть; до текущего инкремента не было provider/model estimate с latency и честным `cost_usd=null`. |
| P0 | QualityReport | implemented and verified | Строгий versioned generation-level report строится из repair evidence, сохраняется с generation job и входит в benchmark; malformed/legacy evidence не принимается как валидное. |
| P0 | История вариантов | implemented and verified | Immutable `ProjectVersion`, parent/provenance и scan candidates. |
| P1 | Smart low-poly preset | partial | Verified triangle decimation/LOD/UV есть; автоматической quad-retopology нет и UI это честно сообщает. |
| P1 | Retexture + PBR | partial | Paint/material/PBR-aware exports есть; provider AI retexture/rebake отсутствует. |
| P1 | Background removal/de-light | implemented and verified | U2-Net/rembg object masking работает; отдельного de-light шага нет. |
| P1 | Segment parts | partial | Геометрический split с закрытыми частями есть; semantic segmentation (голова/тело/аксессуары) отсутствует. |
| P1 | Print repair | implemented and verified | Diagnostics, repair, printable gate и negative tests. |
| P1 | STL/3MF | implemented and verified | Реальные exporters и printable acceptance. |
| P1 | Blender send/open | missing | Есть файлы/экспорт, но нет безопасного Blender handoff/worker contract. |
| P1 | OpenClaw MCP tools | implemented and verified | Официальный MCP SDK публикует узкий typed stdio surface `providers/estimate/generate/get_job/benchmark` поверх собственного API. User-scoped bearer token остаётся env-only и дополнен обязательным project allowlist; remote HTTP запрещён, запуск требует одноразовой request-bound estimate receipt, подтверждения caller и idempotency key; storage/delete/arbitrary Blender code намеренно не экспортируются. |
| P2 | Auto rig + animation | missing | Нет armature/weight validation и provider workflow. |
| P2 | Magic Brush | partial | Локальная face/region paint есть; AI texture inpaint/rebake отсутствует. |
| P2 | Split + connectors | implemented and verified | Watertight parts, dowels/connectors и tests. |
| P2 | Multi-color print | partial | Paint/material-to-tool/G-code путь развивается; нет полного semantic color split → 3MF vendor handoff. |
| P2 | Smart print layout | implemented and verified | Split layout/build-plate preview и print queue существуют. |
| P2 | DCC Bridge Unity/Unreal | missing | GLB/FBX export есть, one-click bridge/project import отсутствует. |
| P2 | Marketplace publishing | implemented and verified | Listings, artifacts, purchase/delivery, moderation и package integrity. |
| P3 | Scene compose | implemented and verified | Versioned multi-object scene graph, transforms, instances и export. |
| P3 | Text-to-animation | missing | Нет motion provider/clip artifact contract. |
| P3 | AI video from 3D | missing | Video-frame import существует, но generation/render-to-video pipeline отсутствует. |
| P3 | Learnable provider router | partial | Router v1 применяет server-side purpose priority и fail-closed budget/latency/privacy/retention/training policy; benchmark telemetry и обучаемый выбор ещё отсутствуют. |
| P3 | Fine-tuning Hunyuan | externally blocked | Нужны выбранные weights/license, NVIDIA GPU и benchmark corpus. |
| P3 | Большие AI-миры/ландшафты | partial | Site plan, terrain, exterior reconstruction и scenes есть; text/image-to-world provider отсутствует. |

## Опыт каждого сервиса, который переносим

- **Meshy:** единая цепочка операций, preview-first, цена перед шагом, следующий шаг без
  повторной загрузки, но без обещания production-ready.
- **Tripo:** отдельные Detailed/Game presets, wireframe рядом с material preview,
  compatibility graph и измеряемый triangle budget.
- **Hi3D:** отдельный print wizard, split/connectors/multicolor/layout и template-first UX.
  Большая часть инженерного print ядра у Sova уже есть; нужен единый мастер и 3MF handoff.
- **YVO3D:** geometry и surface как отдельные версии, fidelity/creativity/adherence,
  retexture без изменения mesh и серверная оценка стоимости.
- **Hunyuan:** self-hosted fallback, раздельные Shape/Paint, seed/model-version
  reproducibility и возможность заменить движок за стабильным публичным API.

## Очередь внедрения

1. **Provider-neutral foundation (текущий блок):** нормализованные request/status/result,
   capabilities+estimate, durable provider attribution, raw+normalized lineage и базовый
   QualityReport поверх существующего Shap-E. Старый `/generate-mesh` остаётся совместимым.
2. **Image/multiview vertical:** выполнено. Single-image идёт через Shap-E; 4–8 перекрывающихся
   object views — через отдельный локальный COLMAP route. Оба пути сохраняют source lineage,
   проходят repair/normalization, а multi-view отказывается при <4 зарегистрированных камерах.
3. **Automatic normalized GLB:** выполнено для text/image Shap-E: sandbox generation → repair →
   GLB export/integrity, raw STL сохраняется отдельно. Расширять тот же инвариант на новые adapters.
4. **Router v1:** purpose routing, budget/latency guard и privacy/retention/training consent
   реализованы fail-closed. Следующие границы: versioned server-side SaaS price config и
   подтверждённая provider deletion policy для каждого подключённого adapter.
5. **Benchmark/telemetry:** provider/model/version/mode/purpose агрегат теперь связывает
   terminal cost, latency, QualityReport и последние append-only good/bad/fixed outcomes каждого
   участника; unrated и mixed не считаются принятыми. Остаток — наполнить 30-object corpus и
   учитывать ручное время.
6. **Surface/game/print adapters:** Tripo game, Hi3D print, Meshy character; YVO только после
   A/B и проверки лицензии/SLA.
7. **MCP/DCC:** минимальный Sova MCP поверх собственного API выполнен и проверен. Следующая
   незаблокированная граница — sandboxed Blender worker с фиксированными операциями и явные
   Unity/Unreal handoff contracts; произвольный Python через MCP не допускается.

## Внешние решения, которые нельзя выдумывать

- API credentials, тариф/SLA и data-retention условия каждого SaaS.
- Разрешение на отправку личных фото внешнему провайдеру.
- GPU profile/region и лицензия Hunyuan для self-host.
- Benchmark winner: до единого набора исходников это неизвестно.
