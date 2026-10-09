# Разбор интерфейсов KIRI Engine и Polycam (по скринам владельца, 44 шт.)

Источник первоначального разбора: скриншоты приложений на iPhone, присланные владельцем
(1–44). На 06.10.2026 доступные официальные справки повторно проверены и сведены в новый
раздел ниже; форумы, отзывы и YouTube не используются как доказательство функций.

## Что у них сделано хорошо

| Приём | Где виден | Что с ним у нас |
| --- | --- | --- |
| Главная кнопка «+» по центру/справа, под ней готовые сценарии, сгруппированные по технологии | KIRI (меню «+»), Polycam («Что вы хотите создать?») | **Сделано:** центр «Создать» (web/desktop/tablet) и шторка «+» (mobile) из общего реестра |
| Перед съёмкой — короткая подготовка: шаги с галочками, картинка, один совет на шаг | Polycam «Creating a 3D Object / Space», KIRI подсказка | **Сделано** как чек-лист и степпер; **картинок/анимаций нет** |
| Счётчик кадров с минимумом и максимумом прямо в съёмке | KIRI (0/150, «минимум 20») | **Сделано** на mobile: полоса с отметкой минимума 12 (минимум API), ориентир по теме |
| Перед обработкой — выбор метода, качества, текстуры, формата словами «для чего это» | KIRI «Редактировать» | **Частично:** контракты и API принимают method/quality/texture/mask; quality реально децимирует, mask запускает U²-Net, exterior сохраняет фото-текстуру. Gaussian splats пока честно не поддерживаются |
| Сравнение фотограмметрии и сплатов таблицей | Polycam | Данные есть (`METHOD_COMPARISON`), экрана нет — нет метода сплатов |
| Комнаты: «продолжить новым сканированием», выбор комнат, общий план | Polycam | **Частично:** один RoomPlan-скан даёт метрический серверный план и «+ Комната» есть; объединения нескольких RoomPlan-сессий/StructureBuilder нет |
| Результат скана: колонка круглых кнопок (пустая комната, тема, измерение, план, правка), снизу «Экспорт» | Polycam | Не сделано |
| Библиотека: поиск, фильтры, сортировка, карточки, «Черновик», видеопомощь | Polycam, KIRI | **Сделано** на web и mobile, включая canonical thumbnails проектов/версий; видеопомощи нет |
| Онбординг из трёх экранов | KIRI | **Сделано** (web) без картинок |
| Загрузка готовых снимков с устройства | KIRI меню «Фотоскан» | **Сделано** на mobile («Из галереи»), кадры без позы; видео нет |
| Загрузка с прогрессом, «не закрывайте окно», «Отмена»; уведомление о готовности | KIRI | **Частично:** настоящая сквозная отмена job и web system notification готовы; отдельный modal/mobile notification UX и полный upload-progress ещё нет |
| Исследовать: галерея сообщества, ленты по типам | KIRI | **Частично:** лента «Исследовать» из маркетплейса на библиотеке (скрыта, если на полке пусто); лент «по типам» нет |
| Подписка/скидка баннером на главной | KIRI | Намеренно не берём |

## Что у них сомнительно, и мы делаем иначе

- Переключатель «Обучить AI» включён по умолчанию → у нас обучение и публичность **выключены**,
  пока человек явно не согласится (см. `docs/SELF_LEARNING_PLAN.md`).
- Минимум 20 кадров как жёсткое правило → у нас минимум равен тому, что реально требует API (12).
  Мы не обещаем того, чего не проверяем.
- Платные «PRO»-замки на качестве — не берём; плотность и текстуры не должны быть за стеной.

## Куда мы можем быть сильнее

Точное редактирование (сетка, выбор вершин/рёбер/граней, круглые и квадратные детали, накатка),
2D-разметка плана пинами и облаками, экспорт под печать/игры/CAD в одном продукте, версии
с откатом. Этого в показанных экранах у конкурентов нет.

## Повторный функциональный аудит 06.10.2026

Этот раздел дополняет первоначальный разбор скриншотов официальной документацией
актуальных продуктов. Сравниваются проверяемые классы функций, а не обещание «скопировать
весь Blender»: SOVA сохраняет единый сценарий scan → edit → plan/print и берёт только те
возможности, которые полезны в этом сценарии.

Источники: [Blender Manual](https://docs.blender.org/manual/en/latest/modeling/meshes/introduction.html),
[Blender modifiers](https://docs.blender.org/manual/en/latest/modeling/modifiers/introduction.html),
[AutoCAD meshes](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Core/files/GUID-A6232957-5039-4AB7-8B1D-8FD0AD98F77B.htm),
[AutoCAD mesh/solid conversion](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Core/files/GUID-FABC5079-9078-468A-8AAD-E61FEAD73815.htm),
[3ds Max retopology](https://help.autodesk.com/cloudhelp/2026/ENU/3DSMax-Retopology/files/GUID-57B77A00-5300-47CB-99E1-22B9C536B060.html),
[SketchUp Solid Tools](https://help.sketchup.com/en/sketchup/modeling-complex-3d-shapes-solid-tools),
[SketchUp extensions](https://help.sketchup.com/en/extension-warehouse/getting-started-extension-warehouse),
[OrcaSlicer wiki](https://github.com/OrcaSlicer/OrcaSlicer/wiki/),
[Prusa variable layers](https://help.prusa3d.com/article/variable-layer-height-function_1750),
[Prusa paint-on supports](https://help.prusa3d.com/article/paint-on-supports_168584),
[Cura Cloud](https://ultimaker.com/software/cura-cloud/),
[Polycam modes](https://learn.poly.cam/hc/en-us/articles/48565771018772-Which-Capture-Mode-Should-I-Use),
[Polycam Space Mode](https://learn.poly.cam/hc/en-us/articles/36655587097620-How-to-Use-Space-Mode-LiDAR-Devices),
[KIRI Engine](https://play.google.com/store/apps/details?id=com.kiriengine.app),
[KIRI video API](https://docs.kiriengine.app/photo-scan/video-upload/),
[Planner 5D Home Scan](https://support.planner5d.com/en/articles/16109431-about-home-scan),
[Planner 5D creation modes](https://support.planner5d.com/en/articles/13038612-how-to-create-a-new-project).

### Сетки сцены и моделей

| Проверка | Статус SOVA | Доказательство/граница |
| --- | --- | --- |
| Полевая 3D-сетка | **Реализовано и проверено на web/desktop** | `ModelViewer` рисует адаптивную сетку; Studio включает/выключает её |
| Шаг и привязка | **Реализовано и проверено на web/desktop** | шаг в мм, snap и плоскости симметрии X/Y/Z в `ModellingPanel`/`topology.ts` |
| Сетка самой модели | **Реализовано и проверено на web/desktop** | реальные сваренные вершины/рёбра/грани; Solid+Wire, Wireframe, X-ray; выбор кликом/рамкой |
| 2D-сетка плана | **Реализовано** | переключаемая сетка 1 м и привязка к плану |
| Те же pro-инструменты на mobile | **Реализовано в коде, device acceptance не пройден** | topology/select, пять прямых mesh-правок, grid/snap/symmetry и Layers используют настоящие API/версии; новая рабочая область собирает их в адаптивный phone/tablet shell. Touch-feel и GPU-бюджеты ещё не проверены на физическом устройстве |

### Рабочая область редактора — референсы владельца 09.10.2026

Новый набор из десяти phone/tablet-экранов рассматривается как карта возможностей, а не
готовый макет. В SOVA сохраняются собственные контракты, OperationPlan и неизменяемые
версии. Базовая нераскрашенная модель нейтрально-белая; оранжевый остаётся цветом действия
и выделения, а цвет самой геометрии появляется только после явной покраски пользователя.

| Класс возможности из референсов | Состояние SOVA после сверки | Граница |
| --- | --- | --- |
| Отдельная phone/tablet-компоновка | **Реализовано в mobile-коде** | phone: viewport → горизонтальная лента инструментов → prompt → вкладки; tablet: rail слева, viewport/prompt в центре, inspector справа |
| Единый inspector «Объект / Проверка / Версии / Экспорт» | **Реализовано** | вкладки вызывают существующие реальные resize, print-analysis, immutable rollback и export jobs, а не декоративные кнопки |
| Белая модель до покраски | **Реализовано** | STL получает тёплый белый PBR-материал; GLB с пользовательскими vertex colours сохраняет собственные цвета |
| 2D/3D в viewport | **Реализовано** | 3D использует perspective orbit; 2D — настоящую orthographic top camera с pan/zoom. Это проекция модели, не отдельный серверный floor-plan editor |
| Полевая сетка | **Реализовано** | Z-up grid лежит под моделью, визуальный шаг синхронизируется с mobile grid setting |
| Выбор object/face/edge/vertex | **Частично** | object + face/edge/vertex есть; отдельный component-kind `body/object` внутри topology API не нужен. Lasso/box-select на mobile остаётся пробелом |
| Move/scale/rotate/extrude context tools | **Частично** | move/extrude/inset/delete/bevel и точные общие размеры работают; универсальные transform gizmo scale/rotate для произвольной component-selection ещё не перенесены в mobile |
| Paint/material/layers | **Частично** | цвет областей и mesh modifier Layers работают; полноценные material slots, shader/texture layers и прозрачность по слоям отсутствуют |
| Print check with progress and parameters | **Частично** | реальный analysis и warnings доступны в workspace; printer/material/layer-height/nozzle presets остаются в slicer, не дублируются пока в project inspector |
| Undo/redo | **Частично** | immutable versions и rollback работают; отдельные одношаговые undo/redo-кнопки в mobile workspace ещё не добавлены |
| STL/3MF/GLB export in workspace | **Реализовано** | кнопки запускают server export job, получают asset и открывают signed download URL; STEP/IGES остаются Pro/CAD-путём web Studio |
| Постоянный text/voice prompt | **Реализовано** | prompt, фото, voice и hands-free доступны непосредственно под viewport |

### Полный сценарий Sova 01–20 — референсы владельца 09.10.2026

Этот набор охватывает не один экран, а путь от выбора задачи до скана здания и сравнения
версий. Статус ниже проверен по текущим routes, shared contracts, API/worker и mobile/web
клиентам. «Частично» означает, что реальный путь существует, но показанная граница UX или
домена отсутствует; внешний макет не считается реализованной функцией.

| № | Возможность из референса | Статус SOVA | Подтверждённая граница |
| --- | --- | --- | --- |
| 01 | Главная с задачами «предмет / комната / дом / фасад / скан» | **Реализовано** | Общий `CREATE_SCENARIOS` ведёт в настоящие generate/scan/model flows на web и mobile; библиотечные карточки теперь получают канонические thumbnail-изображения |
| 02 | Библиотека с поиском, фильтрами, сортировкой и превью | **Реализовано в коде** | Поиск/фильтры/сортировка/действия и canonical PNG thumbnails текущих проектов и immutable-версий подключены на web/mobile; реальный визуальный проход экранов ещё не выполнен |
| 03 | Модель по описанию с фото/эскизом/голосом, размерами и вариантами | **Частично** | Prompt, фото, voice, размеры, AI jobs и несколько preview-вариантов существуют; отдельного sketch-input и собранного mobile-экрана «вариант 1/3 + файлы результата» нет |
| 04 | Четыре фото предмета с обязательными ракурсами и проверкой качества | **Реализовано как deterministic gate** | Web/mobile имеют отдельные front/right/back/left slots, блокируют неполный набор, low resolution/compression, extreme aspect и точные повторы и передают AI канонический порядок. Semantic vision-classifier стороны и автоматическая оценка фона не заявляются: фон пока остаётся явной инструкцией человеку |
| 05 | Круговая съёмка предмета с картой покрытия, экспозицией и кадрами | **Частично** | Реальная capture-сессия, счётчик/минимум, подсказки и frame quality существуют; нет live sphere/pose coverage, ручной экспозиции и turntable-specific capture UI |
| 06 | Пятиэтапная обработка с mesh/texture preview и локальными предупреждениями | **Частично** | Реальные upload/reconstruction stages, отмена, quality report и warnings есть; нет интерактивного split «texture ↔ mesh», per-photo warning strip и pause/resume processing UX |
| 07 | Адаптивная рабочая область модели | **Реализовано в mobile-коде** | Phone/tablet shell, белая базовая модель, grid, selection, prompt и inspector работают; физический touch/layout acceptance ещё не пройден |
| 08 | Точная правка vertex/edge/face, transforms и mesh operations | **Частично** | Выбор topology, move/extrude/inset/delete/bevel, grid/snap/symmetry и версии работают; component scale/rotate gizmo, lasso/box-select и полный набор операций референса отсутствуют на mobile |
| 09 | Scene tree, слои и modifier stack | **Частично, mobile scene hierarchy реализована** | Web/mobile читают один server-side immutable scene graph: mobile теперь раскрывает дерево, выбирает parent без циклов, меняет имя/visibility, group/ungroup, duplicate-as-instance и make-unique с созданием новой версии; mesh modifier Layers остаются отдельной реальной панелью. Material layers и отображение всех multi-object nodes в mobile viewport ещё отсутствуют |
| 10 | Проверка печати, габариты, ракурсы и STL/3MF/GLB | **Частично** | Настоящий print analysis, размеры и export jobs доступны в workspace; нет thumbnail-ракурсов и printer/material/nozzle/layer presets внутри project inspector |
| 11 | RoomPlan live scan комнаты | **Реализовано в коде, внешняя приёмка заблокирована** | Нативный iOS module, RoomPlan geometry, USDZ и API-plan path есть; Swift/signing и физический LiDAR-iPhone/iPad не проверены на Linux-хосте |
| 12 | Один экран «план комнаты ↔ 3D» с мебелью и размерами | **Частично** | Серверный метрический plan и 3D-version создаются из RoomPlan, web plan умеет размеры/аннотации; одновременный linked pane и mobile floor-plan editor отсутствуют |
| 13 | Дом с нуля: контур, стены, проёмы и автоплан | **Частично** | Контур дома, server plan и автокомнаты/двери работают для прямоугольника; L/T/free-form auto-layout, этажи и отдельный mobile plan screen не сделаны |
| 14 | Быстрый конструктор дома с каталогом мебели | **Частично, real-scale web/desktop increment** | Web Studio получил пять реальных параметрических STL-предметов, точную XYZ/rotation расстановку в отдельные immutable scene nodes и viewer/export parity. До референса остаются drag/drop по комнате, AI furnishing, расширяемая asset library и mobile multi-object renderer |
| 15 | Связанные «План ↔ Модель / Фото ↔ Модель / Было ↔ Стало» | **Реализовано по core-сценариям** | Mobile Plan↔Model и calibrated Photo↔Model имеют phone switch и tablet resizable/swap/expand split; web/mobile versions получили Source↔Current reveal. Perspective matching, arbitrary reference anchors и synchronized dual-3D orbit остаются расширениями |
| 16 | Семантический фасад с нуля: этажи, крыша, проёмы, материалы | **Частично, facade-editor MVP** | Web Studio собирает новый exact facade-version из доказанного server-side lineage прямоугольного house-box: 1–3 этажа, толщина стен, none/flat/gable roof и bounded schedule окон/дверей по четырём сторонам. API fail-closed отклоняет сканы/import, непрямоугольные дома, forged provenance и broken lineage. До полного референса остаются surface material assignments, произвольные контуры/крыши и mobile flow |
| 17 | Пошаговая съёмка четырёх фасадов с покрытием | **Реализовано** | Mobile ведёт front/right/back/left и optional roof, хранит resume-state, считает coverage и не разрешает завершить без обязательных секций |
| 18 | Сборка здания, масштаб по опорному размеру и quality gate | **Реализовано backend; UI частично** | Exterior worker требует связную COLMAP-модель, масштабирует по измерению, проверяет registered views/coverage и создаёт textured GLB; отдельного assembly review screen как в референсе нет |
| 19 | Семантическая правка фасада после скана | **Частично** | Скан становится обычной immutable editable version; доступны selection, mesh/CAD edit, paint и versions. Нет façade-aware surface cleanup/opening/material workflow и локального before/after slider |
| 20 | Source ↔ current слайдер и визуальная шкала версий | **Реализовано как render comparison** | Web/mobile история показывает thumbnails immutable-версий и draggable source/current reveal; source выбирается нажатием версии, а restore остаётся явным созданием новой версии. Live dual-3D orbit и semantic geometry diff не заявляются |

Приоритет по зависимости: единый preview/thumbnail artifact и Plan ↔ Model MVP уже закрыты.
Следом идут mobile parity и project-inspector presets; thumbnails, Plan↔Model, calibrated mobile
Reference↔Model, guided multi-photo, source/current reveal, первый real-scale furniture increment
и bounded façade-editor MVP уже закрыты. Полный room furnishing и произвольный façade editor
остаются отдельными большими эпиками; их нельзя честно выдавать за косметическую доработку
текущего workspace.

### Blender / AutoCAD / 3ds Max / SketchUp

| Класс возможностей | Статус SOVA | Подтверждённый пробел |
| --- | --- | --- |
| Точное твёрдотельное CAD-моделирование | **Реализовано для основных solids и bounded surface CAD** | B-Rep-примитивы, extrusion, boolean, holes, shell, fillet/chamfer, patterns, mirror, loft, sweep и revolve проходят единый OCCT-путь. Замкнутый sketch поддерживает lines, circular arcs, interpolated B-splines и rational NURBS curves на произвольной плоскости с проверяемыми constraints. T-246 добавил exact rational tensor-product NURBS patch, утолщаемый в замкнутый solid. T-247 извлекает из выбранной связной planar face-области exact line-profile и начинает из imported/scanned mesh новый параметрический feature tree; curved/hole/non-planar recovery и periodic/trimmed/multi-patch surfaces ещё не сделаны |
| Прямое polygon/mesh-редактирование | **Частично** | move/extrude/inset/delete/bevel и детали есть; нет loop cut, knife, bridge, dissolve, proportional editing и проверки самопересечений после каждой свободной правки |
| Неразрушающий modifier stack | **Реализовано для B-Rep и прямых mesh-правок** | T-239: типизированный B-Rep feature stack хранит enabled-состояние и пересобирается через OCCT. T-240: imported/scanned mesh хранит move/extrude/inset/delete/bevel/detail как отдельные типизированные шаги с допуском; выключение и перестановка пересчитывают активные шаги от исходного immutable asset в новую версию. Более широкий procedural stack (subdivision/array/deform) остаётся расширением |
| Subdivision/sculpt/retopology | **Частично** | decimation/LOD есть; нет subdivision sculpting и автоматической чистой quad-retopology уровня 3ds Max/KIRI |
| UV и материалы | **Частично** | авто-UV/PBR на экспорт и фото-атлас скана есть; нет ручного UV editor, слоёв материалов, shader graph и texture painting |
| Сцена и библиотека объектов | **Частично** | каталог/версии/происхождение есть; нет иерархии сцены, групп/коллекций, инстансов и 3D Warehouse/Extension Warehouse масштаба |
| Риг, анимация, симуляции, production render | **Отсутствует** | armature/keyframes, cloth/fluid/particles и Cycles/Arnold-класс рендера не входят в текущий путь продукта |
| Расширения/скрипты | **Отсутствует** | нет безопасного plugin API или Python/Ruby-подобной системы расширений |
| Строительные чертежи | **Частично** | 2D-план, размеры, разметка и PDF/PNG есть; нет листов, viewports, dimension styles, слоёв и DWG/DXF round-trip уровня AutoCAD/LayOut |

Точные B-Rep loft/sweep/revolve и sketch constraints реализованы 07.10.2026. T-239
закрыл параметрический feature stack, T-240 — недеструктивный стек прямых mesh-правок,
T-241/T-242 — multi-object hierarchy и node-specific editing. T-243–T-246 добавили exact
curves, arbitrary sketch planes и bounded rational NURBS surfaces. T-247 закрыл bounded
automatic selected mesh→CAD line-profile для одной planar face-области. Распознавание
curved/hole/non-planar профилей и periodic/trimmed/multi-patch surface CAD остаётся
отдельным расширением точного ядра. Риг, симуляции и фоторендер —
самостоятельные большие эпики, а не скрытые «небольшие» пробелы.

### Слайсер против OrcaSlicer / PrusaSlicer / Cura / Bambu Studio

| Функция | Статус SOVA |
| --- | --- |
| Реальный FDM G-code, периметры, линии/соты, skirt | **Реализовано** |
| Grid и tree supports, interface и Z-gap | **Реализовано**: paint-on blocker/enforcer проходят до реального grid/tree planner; зрелый organic planner уровня top-слайсеров остаётся отдельным улучшением |
| Размещение на столе, поворот, seam сзади, travel 2-opt | **Реализовано** |
| Калибровка размеров/потока и поправки по отчёту печати | **Реализовано** |
| Сплошные верхние/нижние оболочки, включая ступени | **Реализовано 06.10.2026**: настраиваемые 0–20 слоёв, не смешиваются с sparse infill |
| Variable/adaptive layer height | **Реализовано 06.10.2026**: geometry-driven schedule, настраиваемый диапазон, фактические Z и экструзия каждого слоя |
| Gyroid/cubic/lightning и расширенный infill | **Отсутствует** |
| Ironing, bridge-specific flow/speed, scarf/painted seam | **Отсутствует** |
| Пользовательские brim/raft/mouse ears | **Частично**: brim есть как автоматическая поправка после отчёта, ручного управления и raft нет |
| Multi-material, purge/wipe tower | **Отсутствует** |
| Полный цветной toolpath preview | **Реализовано 06.10.2026**: web разбирает все слои готового G-code и отдельно показывает perimeter, solid/sparse infill, support/interface, skirt/brim, travel и неизвестные legacy-линии |
| Printer/material/process profiles | **Частично**: принтер, материал, калибровка и OctoPrint есть; нет полного набора speed/accel/temp/cooling overrides |
| Resin slicing | **Отсутствует** и явно отклоняется |

Точный CAD-блок loft/sweep/revolve и sketch constraints закрыт 07.10.2026.
Следующие slicer-пробелы — расширенные infill, bridge/ironing/seam и ручные adhesion
настройки. Multi-material требует отдельной модели принтера/экструдеров и не должен
имитироваться одним G-code-потоком.

### Planner 5D / Polycam / KIRI Engine на mobile

| Функция конкурентов | Статус SOVA |
| --- | --- |
| Единый выбор object/room/building/CAD/print и подготовка к съёмке | **Реализовано** |
| Фотограмметрия с фото, quality/texture/mask до обработки | **Реализовано**, маскирование и exterior COLMAP проходят настоящие worker-пути |
| LiDAR-комната → 3D + метрический 2D-план | **Частично**: код и EAS/autolinking готовы; физический LiDAR/Swift не проверены |
| Несколько комнат/этажей одной непрерывной сессией | **Отсутствует**: нет StructureBuilder/common coordinate frame |
| Gaussian splats | **Отсутствует** и честно возвращает `not_supported_yet` |
| Shiny/featureless NSR/NeRF | **Отсутствует** |
| Video-to-scan и 360 panorama | **Отсутствует**; галерея принимает фото без позы |
| Crop/plane/sphere/brush cleanup на результате скана | **Частично**: общая mesh-edit есть на web, mobile result UX не собран |
| Quad retopology и AI PBR | **Отсутствует**; есть decimation/LOD и настоящий фото-атлас, но не эти функции |
| Floorplan from uploaded photo/blueprint/video | **Отсутствует** |
| Редактируемые стены/двери/окна и мебельный интерьер | **Частично**: план и разметка есть, но нет каталога мебели/AR placement/AI furnishing уровня Planner 5D |
| 360 walkthrough, spatial report, DXF/CSV plan export | **Частично**: 3D-view, измерения, ведомость, PDF/PNG есть; нет panorama/walkthrough и DXF/CSV |
| Live collaboration/comments | **Реализовано для разметки плана** с revision/409/merge/live-room |

Внешне заблокировано: физическая проверка RoomPlan требует LiDAR iPhone/iPad и EAS signing.
Провайдер gaussian splats/NSR отсутствует; до выбора лицензии, вычислительного бюджета и формата
хранения эти методы нельзя отмечать как готовые.
