# Пустая комната после RoomPlan-скана: bounded first increment (design)

Status: design only, product code не менялся. Документ закрывает design pass для item 43
`docs/COMPETITOR_UI_ANALYSIS.md` ("Пустая комната после скана") и опирается на прямое
чтение `apps/mobile/modules/expo-room-plan/ios/ExpoRoomPlanView.swift`,
`apps/mobile/modules/expo-room-plan/src/ExpoRoomPlan.types.ts`,
`apps/mobile/app/scan/{index,[id]}.tsx`, `services/api/app/engineering/room_plan.py`,
`services/api/app/services/scanning.py`, `services/api/app/jobs/reconstruct_scan.py`,
`services/api/app/models/scanning.py`, `services/worker/worker/importers/usdz.py` и журналов
`docs/{IMPLEMENTED,IN_PROGRESS}.md` — не на предположении, что USDZ уже хранит отдельные
редактируемые предметы.

Решение: **Option A — отдельная параметрическая оболочка только для новых Apple RoomPlan-
сканов**. Это не удаление мебели из исходного mesh. Сервер строит второй asset только из
валидированных структурных RoomPlan-примитивов и переключает просмотр между исходным сканом и
этой оболочкой. **Option B — детекция/маски/удаление/inpainting для произвольного скана — явно
отложен как отдельный большой CV-инкремент**, аналогично тому, как item 34 не был force-fit в
существующий RoomPlan-путь.

## 0. Что есть сейчас и что именно доказано кодом

### 0.1 RoomPlan действительно отличает структуру от объектов

Нативный callback получает `CapturedRoom`, а код обращается к разным коллекциям:

- `processedResult.walls`, `doors`, `openings`, `windows` превращаются в структурированный
  `roomPlan` payload;
- `processedResult.objects` сейчас используется только как `count`;
- USDZ экспортируется отдельно через `processedResult.export(..., exportOptions: .mesh)`.

Это видно в `ExpoRoomPlanView.swift`: live event отдаёт три независимых счётчика
`walls/openings/objects`, а finish event сериализует стены и проёмы, но от объектов передаёт
только число. Следовательно, furniture-vs-structure distinction в native result **есть** и для
Option A не требуется придумывать собственный классификатор.

При этом текущий JS-контракт (`ExpoRoomPlan.types.ts`) сохраняет лишь:

- стены: id, две плановые точки X/Z, высота;
- проёмы: id, parent wall, плановый центр X/Z, ширина и kind;
- предметы: только общее количество.

Важная граница: в persisted payload нет transform/dimensions предмета, его категории или маски,
а для проёма нет вертикального положения и высоты. Поэтому текущих persisted данных достаточно
для 2D-плана, но недостаточно для честной поэлементной видимости мебели и точной 3D-геометрии
окон.

### 0.2 После загрузки USDZ семантика сцены теряется

`services/worker/worker/importers/usdz.py::_merge_meshes` обходит все `UsdGeom.Mesh`, применяет
world transform и объединяет вершины/грани в один `trimesh`. Пути prim, RoomPlan category и
соответствие `CapturedRoom.Object.identifier → faces` не сохраняются. Затем scan reconstruction
чинит/децимирует mesh и записывает один `ScanSession.mesh_asset_id`
(`services/api/app/jobs/reconstruct_scan.py`).

Из этого следует:

- удалить или скрыть конкретный диван из принятого mesh по одному RoomPlan object id нельзя;
- список «Диван / Столик / Тумба / Ковёр / Растение» с работающими eye-toggle нельзя строить
  поверх нынешнего asset — даже если начать передавать названия объектов, face masks всё равно
  отсутствуют;
- «скрыть всю мебель» можно реализовать честно только как показ **другого**, shell-only asset,
  а не как фильтр исходного mesh.

### 0.3 Структурный план уже сохраняется, но только как 2D-проекция

`services/api/app/engineering/room_plan.py` валидирует единый замкнутый контур, снапит его,
сопоставляет openings со стенами и создаёт `FloorPlan`. `scanning.set_room_plan()` сохраняет в
`ScanSession.capture_stats.room_plan` `source=apple_roomplan`, `floor_height_mm`, warnings и
нормализованный `floor_plan`; `scanning.accept()` переносит их в provenance принятой immutable
версии.

Это достаточная основа для размеров стен. Но текущая конверсия намеренно теряет исходный
вертикальный transform проёмов и нормализует X/Z origin, а `PlanWall.thickness_mm=120` —
консервативное значение по умолчанию, не измеренная RoomPlan толщина. Оболочка должна явно
показывать эти допущения, а не называться точной реконструкцией.

### 0.4 Статус ledger всё ещё актуален

`docs/IN_PROGRESS.md`, раздел «Не сделано вообще», по-прежнему говорит: «Экран результата скана
с колонкой действий (пустая комната, тема, измерение, план, правка) ...» не сделан.
`docs/COMPETITOR_UI_ANALYSIS.md`, item 43, также остаётся `Отсутствует`. В коде result-view есть
только Texture/Mesh для одного `mesh_asset_id`; room-shell asset, empty-room toggle и
per-object visibility отсутствуют. То есть формулировка **«не сделано вообще» остаётся точной**
на момент этого design pass.

## 1. Решение по Option A / Option B

### 1.1 Выбран Option A, но с честной границей по данным

Первый инкремент строит **parametric room shell** из RoomPlan walls/openings и пола, выведенного
из валидированного замкнутого wall outline. Furniture objects вообще не входят в builder. В UI:

1. «Исходный скан» показывает существующий repaired/textured mesh без изменений.
2. «Пустая комната» показывает второй shell-only asset.
3. «Скрыть всю мебель» — второй способ включить тот же режим, а не мутация исходной версии.

Это поддерживается реальным разделением коллекций внутри `CapturedRoom` и не требует
сегментации. Но нынешний schema v1 не хранит вертикальные параметры проёмов; поэтому native
bridge сначала получает **backward-compatible schema v2** (§2). Новые captures с v2 получают
feature. Исторические v1 scans не «восстанавливаются» эвристиками и остаются без toggle.

### 1.2 Option B отложен

Для RGB/RGB-depth/обычного scanner mesh и исторического flattened RoomPlan USDZ нужны как
минимум instance segmentation, устойчивое 3D mask-to-mesh соответствие, hole completion/
inpainting, confidence model и ручная коррекция ошибок. Это отдельный CV/geometry продукт, не
расширение `mask_object`: текущая U²-Net маска из items 32/33 убирает фон **до object
reconstruction**, но не различает стены и мебель внутри уже собранной комнаты.

Option B не включается в этот increment и не маскируется fallback-ом на грубую mesh cropping.
Для не-RoomPlan скана API честно возвращает `room_shell_unavailable: unsupported_capture_source`.

### 1.3 Что из референса входит и не входит

| Элемент референса | First increment |
|---|---|
| «Исходный скан» ↔ «Пустая комната» | **Да**, два реальных asset в одном координатном кадре |
| «Скрыть всю мебель» | **Да**, alias переключателя на shell-only view |
| Размеры стен на empty-room 3D | **Да**, из server-validated wall endpoints/height |
| Список распознанных предметов | **Нет**: сейчас persisted только count |
| Eye-toggle каждого предмета | **Нет**: flattened mesh не имеет object→faces mapping |
| Реальное удаление/inpainting в исходной текстуре | **Нет**, Option B |
| Произвольный completed scan, Android, photo-only room | **Нет**, Option B/item 34 |
| Редактирование длины/толщины/материала стены | **Нет**, отдельный item 21 |

## 2. Native payload v2: минимальные данные для оболочки

`RoomPlanCapture` становится versioned union. Отсутствующий `schema_version` трактуется как 1,
чтобы старый development client продолжал загружать план. V2 добавляет данные, которые уже
присутствуют в `CapturedRoom.Surface`; собственного vision inference здесь нет.

```text
RoomPlanCaptureV2
  schema_version: 2
  room_id: string
  walls[]:
    identifier
    transform_m: 4x4 finite affine matrix
    dimensions_m: [width, height, depth]
  openings[]:                 # doors + windows + generic openings
    identifier
    parent_wall_id | null
    kind: door | window | opening
    transform_m: 4x4 finite affine matrix
    dimensions_m: [width, height, depth]
```

Почему full surface transform, а не ещё несколько 2D полей:

- он сохраняет исходный RoomPlan coordinate frame для совмещения с USDZ;
- вертикальный центр + dimensions дают sill/top окна без guessed 900/2100 mm;
- wall local X и local Y позволяют детерминированно проектировать opening на parent wall;
- матрица является исходным измерением RoomPlan, а не вычисленной JS-эвристикой.

Floor не делается обязательным native полем. Текущий поддерживаемый code path не обращается к
`processedResult.floors`, а минимальная версия iOS/API для него в репозитории физически не
скомпилирована. Для bounded single-room contour floor строится как планарный polygon из уже
валидированного wall loop на median нижней отметке стен. Если будущая подтверждённая версия
RoomPlan даст floor surface, его можно добавить как v3 и сверять с derived polygon; first
increment не зависит от неподтверждённого SDK API.

V2 bridge по-прежнему может отдавать прежние `a_m/b_m/height_m/center_m/width_m` для старого JS,
но сервер вычисляет свой shell spec только из validated v2 transforms/dimensions. Объекты в v2
не сериализуются: без face mapping это создаст видимость готовности per-object toggle, которой
нет.

## 3. Server canonicalization и fail-closed `RoomShellSpec`

`set_room_plan()` не хранит client payload как исполняемый recipe. Он валидирует v2 и создаёт
неизменяемый server-owned `RoomShellSpec` рядом с существующим `floor_plan`:

```text
RoomShellSpec v1
  source: apple_roomplan
  source_room_id
  source_to_shell_mm: 4x4 matrix  # output of load_mesh_mm / native surfaces converted to mm
                                  # -> one SOVA-mm, Z-up frame; no second unit scaling
  outline_mm[]                    # один простой замкнутый polygon
  floor_z_mm: 0
  floor_visual_thickness_mm: 20   # declared approximation
  walls[]:
    source_id, a_mm, b_mm, height_mm, thickness_mm=120
  openings[]:
    source_id, wall_index, offset_mm, width_mm,
    bottom_mm, height_mm, kind
  approximations[]                # wall_thickness, floor_thickness, no_ceiling
```

Один helper владеет преобразованием осей/единиц для **обоих** asset: он применяет ту же
`source_to_shell_mm` matrix к уже переведённому `load_mesh_mm` USDZ mesh перед
repair/decimation и к RoomPlan surfaces после отдельного перевода metres→millimetres, но до
shell build. Нельзя отдельно hardcode X/Z→X/Y в API и другую перестановку осей в worker и нельзя
повторно умножать USDZ mesh на 1000. Mapping проверяется fixture-тестом на совпадение wall
endpoints и source mesh; при расхождении выше bounded tolerance shell не публикуется.

Дополнительные проверки поверх существующего `floor_plan_from_room_plan`:

- finite affine matrices, non-collapsed orthonormal basis с допустимым RoomPlan drift;
- 3–128 стен, 0–256 проёмов и bounded operation count;
- единый простой wall loop, длины/perimeter в уже существующих пределах;
- median floor/top spread: стены не могут расходиться по нижней отметке более чем на 100 mm и
  по высоте более чем на 300 mm; большее расхождение — `non_planar_room_shell`, не averaging;
- opening должен однозначно попасть на одну стену, полностью лежать внутри её длины и высоты;
- overlapping openings на одной стене отклоняются;
- door/generic opening может касаться пола в пределах 100 mm; window обязан иметь положительный
  sill; никакие стандартные высоты не подставляются;
- `thickness_mm=120` и floor slab 20 mm маркируются как visualization assumptions. Они не
  участвуют в строительной смете как измеренные значения.

Если v2 не проходит эти проверки, существующий 2D plan/upload result ведёт себя по прежним
правилам, но shell получает стабильную unavailable-reason. Нельзя проваливать весь scan только
из-за дополнительного представления.

## 4. Генерация геометрии

### 4.1 Детерминированный builder

Новый bounded builder принимает только `RoomShellSpec`:

1. Создаёт floor slab по `outline_mm`, вниз от `floor_z_mm`, чтобы внутренняя отметка пола
   оставалась 0.
2. Для каждой стены создаёт box вдоль `a→b`, толщиной 120 mm внутрь/наружу от centerline и
   высотой `height_mm`.
3. Для каждого opening вычитает axis-aligned в локальной системе стены cutter с небольшим
   техническим запасом только по толщине стены. Width/height/bottom берутся из spec, не из
   категорийных defaults.
4. Стены и пол объединяются в один shell mesh; потолок не создаётся, чтобы интерьер был виден
   сверху и чтобы не выдавать неотсканированную плоскость за измерение.
5. Пишет STL (или GLB с одним нейтральным материалом, если общий viewer требует material) в mm
   и метаданные `kind=room_shell`, `source=apple_roomplan`, `spec_schema_version=1`.

Реализация должна переиспользовать existing exact `OperationPlan`/kernel primitives
(`create_box`, transform, boolean cut/fuse и planar sketch extrusion), а не вводить второй
непроверенный mesh-CSG engine. `services/api/app/engineering/house_walls.py` является полезным
паттерном для wall boxes/transforms, но не может быть вызван как есть: его собственные
assumptions прямо говорят, что floor slabs и openings не генерируются.

### 4.2 Где запускается builder

Shell строится в `reconstruct_scan` после успешной реконструкции RoomPlan source mesh и до
перевода session в `ready`. Результаты независимы:

- основной mesh остаётся обязательным результатом;
- shell — дополнительный artifact;
- ошибка shell записывается в report и скрывает toggle, но не превращает хороший исходный scan
  в `failed`;
- retry/resume идемпотентно переиспользует content-addressed shell asset для того же canonical
  spec.

Это позволяет показать оба вида **до** Accept, как требует scan-result flow. Генерировать shell
только после `accept()` поздно: текущие mobile/web result pages показывают модель и дают Keep/
Retry именно пока `ScanStatus.ready`.

## 5. Хранение, API и immutable version

### 5.1 Минимальная миграция

- `scan_sessions.room_shell_asset_id UUID NULL FK assets(id) ON DELETE SET NULL`;
- новое enum-значение `AssetRole.room_shell`;
- `room_shell` добавляется в `CONTENT_ROLES`, потому что это содержательная геометрия принятой
  версии, а не regenerable thumbnail/preview.

Не класть asset id только в JSON report: FK нужен, чтобы ссылка не пережила удаление asset и
чтобы transfer/authorization tooling могло обнаружить зависимость.

### 5.2 Read contract

`ScanOut` получает `room_shell_asset_id: UUID | null`. Отдельный read-only endpoint
`GET /scans/{scan_id}/room-shell` возвращает только при успешной генерации:

```text
RoomShellOut
  asset_id, format
  source_to_shell_mm: 4x4
  walls[]: {id, a_mm, b_mm, length_mm, height_mm}
  approximations[]
```

Endpoint использует ту же workspace-viewer authorization, что `get_scan`; он не принимает
asset/spec от клиента. Download идёт через существующий signed asset endpoint.

После `accept()`:

- исходный mesh остаётся единственным `AssetRole.model`, поэтому существующие edit/export/
  repair пути не меняют смысл;
- shell прикрепляется к той же version как `AssetRole.room_shell`;
- provenance получает canonical `room_shell` metadata без дублирования бинарника;
- `GET /models/{version_id}/room-shell` возвращает тот же `RoomShellOut` для project viewer.

Нельзя прикреплять shell вторым `model`: `model_asset_of()` выбирает один model без
гарантированного порядка, и это сделает repair/export недетерминированными. Нельзя использовать
`preview`: эта роль уже означает painted preview и может регенерироваться после finalize.

### 5.3 Совместимость и rollout

Порядок выпуска: server/API/contracts → worker → native iOS build → UI flag. Новый server
принимает v1 и v2; старый client продолжает получать обычный plan. Новый client не должен
отправлять v2 в server, который ещё не объявил capability `room_plan_shell_v1`.

Исторические RoomPlan sessions/versions не backfill-ятся: v1 не содержит vertical opening data
и доказанного source-frame transform. Они остаются полностью читаемыми, но endpoint отвечает
404/typed unavailable reason, а UI не показывает toggle.

## 6. UX first increment

### 6.1 Scan result: mobile и web

На `apps/mobile/app/scan/[id].tsx` и `apps/web/src/app/scanner/[id]/page.tsx` segmented control
появляется только если `room_shell_asset_id != null` и room-shell endpoint успешно прочитан:

- **Исходный скан** — текущие Texture/Mesh controls остаются как есть;
- **Пустая комната** — нейтральная shell geometry;
- toggle **Скрыть всю мебель** синхронизирован с тем же state (`true = empty`).

Оба asset загружаются в один viewer scene и получают общий `source_to_shell_mm` transform, поэтому
переключение меняет visibility без повторного auto-frame и сброса orbit/pan/zoom. Нельзя
перемонтировать два независимых viewer и называть это сравнением: current `ModelViewer` при
каждой новой URL заново центрирует geometry и сбрасывает camera radius.

В empty mode над стенами показываются read-only labels `length × height` (метры с двумя знаками)
в midpoint каждой стены; labels скрываются за камерой и проходят bounded declutter (не более 16
одновременно, ближайшие к камере/выбранной стене имеют приоритет). Тап по label подсвечивает
соответствующую стену и показывает точные mm в карточке. Это измеренные RoomPlan length/height;
120-mm thickness помечена «условная визуальная толщина».

Постоянная подпись под toggle:

> Параметрическая оболочка по стенам и проёмам Apple RoomPlan. Это не удаление мебели из
> текстуры; толщина стен и пола показана условно.

Если shell generation не удалась, исходный scan остаётся доступен, а одна спокойная строка
показывает конкретную причину («не хватает высоты проёма», «контур не образует одну комнату»),
без disabled toggle, обещающего недоступную функцию.

### 6.2 После Accept

Тот же control доступен в project viewer, когда current version имеет `room_shell` role. Он
остаётся view-mode, не создаёт версию и не меняет scene-node visibility. Edit/repair/export по
умолчанию продолжают работать с исходным `model` asset. Отдельный export shell не входит в этот
increment; кнопка Export рядом с empty mode должна явно сказать «Экспорт пустой оболочки — позже»
или не показываться, но не выгружать молча исходный scan.

### 6.3 Почему per-object list отсутствует

First increment не рисует декоративные строки «Диван» с неработающими eyes. Чтобы добавить их
позже, требуется отдельный RoomPlan-object increment: сохранить object id/category/transform,
создать каждому object отдельный geometry asset/node **до flattening**, доказать alignment и
только затем связать eye с реальной node visibility. Для arbitrary scan это всё равно не решает
Option B.

## 7. Безопасность и границы отказа

- Shell разрешён только когда server-side canonical spec имеет `source=apple_roomplan` и
  session capability подтверждает `capture_source=apple_roomplan`; один client boolean не
  достаточен.
- Все matrices/numbers finite и bounded; surface count и operation count ограничены до enqueue.
- Shell builder не читает произвольный path из payload: USDZ и spec разрешаются только через
  workspace-owned `Asset`/`ScanSession`.
- `GET .../room-shell` не раскрывает asset другого workspace и использует существующий viewer
  role check.
- Неуспешный shell не блокирует accept исходного скана и не создаёт частичную finalized version.
- При Accept shell asset прикрепляется в той же транзакции, что version. Если FK исчез/не
  принадлежит workspace, accept fail-closed до finalize; исходная ready session остаётся.
- Provenance различает `measured` (wall/opening transforms/dimensions) и `assumed` (wall/floor
  thickness, omitted ceiling). UI и downstream takeoff не смешивают эти классы.

## 8. Проверка и acceptance

### 8.1 Native / physical-device gate

Это обязательный gate, а не необязательная polish-проверка: `docs/IMPLEMENTED.md` и
`docs/IN_PROGRESS.md` прямо фиксируют, что Swift/RoomPlan ещё не компилировался и не проверялся
на физическом LiDAR iPhone/iPad.

На поддерживаемом устройстве нужны минимум три fixture capture:

1. прямоугольная комната: дверь + окно + диван;
2. Г-образная комната: обычный opening + несколько объектов;
3. негативный capture с незамкнутым/неоднозначным контуром.

Для первых двух: v2 matrices/dimensions сериализуются, source и shell совпадают по стенам в
пределах 50 mm после canonical transform, мебель видна только в source view, дверь/окно имеют
правильное вертикальное положение, toggle не сбрасывает camera. Третий остаётся обычным
просматриваемым scan без empty toggle и с typed reason.

### 8.2 Automated tests

- Swift/TypeScript contract: all 16 matrix values, dimensions и kinds проходят bridge без
  перестановки/потери; non-finite не отправляется.
- API schema: v1 backward compatibility; v2 extra/missing/malformed matrices rejected;
  reserved `capture_stats.room_plan` всё ещё нельзя подменить generic PATCH-ем.
- Canonicalization goldens: rectangle/L, reversed wall order, parentless unambiguous opening,
  window sill, out-of-wall/overlap/non-planar failure.
- Geometry goldens: floor + expected wall solids; cutter действительно даёт door/window hole;
  shell bbox/volume finite; нет мебельных components; exact operation count bounded.
- Reconstruction integration: RoomPlan v2 создаёт два artifacts и ready session; shell failure
  создаёт ready source-only session; pause/resume не дублирует assets.
- Accept integration: одна immutable version с ровно одним `model` и одним `room_shell`;
  ordinary scans получают только `model`; cross-workspace shell id rejected.
- Web/mobile UI: control виден только при asset, bulk toggle и segment state эквивалентны,
  camera state сохраняется, labels только в empty mode, unavailable reason честный.
- Regression: existing repair/export/model viewer продолжают выбирать исходный `model`, а не
  shell.

### 8.3 Definition of done

Item 43 можно перевести из «не сделано вообще» в «частично: RoomPlan-only shell» только когда:

- физический LiDAR capture прошёл gate выше;
- mobile и web scan result реально переключают два server-backed asset;
- accepted version сохраняет оба представления без изменения default model semantics;
- UI явно раскрывает approximations и отсутствие per-object removal;
- RGB/photo/scanner paths не получают ложную кнопку.

После этого формулировка item 43 должна всё ещё сохранять остаток: per-object visibility и
arbitrary-scan segmentation/inpainting не реализованы.

## 9. Намеренно отложено

- Option B: segmentation/removal/inpainting для arbitrary scan.
- RoomPlan object inventory и individual eye toggles.
- Texture completion пустых областей: shell остаётся нейтральным parametric material.
- Редактирование стен/проёмов/materials (item 21/22).
- Empty-shell export и замена project head на shell model.
- Несколько RoomPlan-сессий/StructureBuilder в общем frame (T-197).
- Photo-only room capture без LiDAR (item 34).

Эти пункты не блокируют Option A и не должны незаметно войти в его реализацию.
