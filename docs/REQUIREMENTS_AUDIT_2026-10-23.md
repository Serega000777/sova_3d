# Аудит главного ТЗ F-001–F-087 — 23.10.2026, актуализирован 28.10.2026

Первичный контроль: `6655ece`; повторная сверка: `944a4a6` (`main`). Источники истины:

- `docs/v2/01_FEATURE_REGISTRY_80.docx` — F-001–F-080;
- `docs/FEATURE_REGISTRY_ADDENDUM.md` — F-081–F-087;
- сценарии владельца 01–50 и marketplace M01–M10 учитываются отдельно и не меняют знаменатель 87.

Повторная сверка 28.10 заново проверила полный знаменатель `F-001–F-087` по registry,
актуальному Git, маршрутам, generated contracts и тестам. Машинная partition-проверка дала ровно
**55 implemented and verified / 28 partial / 0 missing / 4 externally blocked** без пропусков,
дубликатов и посторонних ID. Поставки после первичного аудита расширили marketplace, mobile
game-ready/integrity/printing, collaboration и reference-пути, но не превратили физическую
приёмку или отсутствующих внешних провайдеров в локально доказанные функции.

Отдельные корпуса не суммируются с главным ТЗ: retained product references `01–100` имеют
собственный аудит **49 verified / 48 partial / 0 missing / 3 externally blocked**, а
marketplace `M01–M10` остаётся отдельной матрицей из десяти partial-строк. Это алиасы и более
детальные acceptance surfaces, а не ещё 110 независимых требований поверх 87 Feature ID.

Все 19 ранее частичных сценариев 01–50 закрыты отдельными проверенными коммитами. №11 не был
одним из этих 19: его Swift/RoomPlan-код существует, но физическая LiDAR-приёмка остаётся внешней.

## 1. Локально закрытые границы

Следующие ID имеют рабочую сквозную границу в текущем коде (домен/worker → API → immutable
version/job → contracts → применимые клиенты) и автоматическую проверку:

`F-001`, `F-003–F-011`, `F-013`, `F-016–F-018`, `F-021–F-025`, `F-027`,
`F-030–F-032`, `F-034–F-036`, `F-039–F-042`, `F-045–F-047`, `F-049`, `F-051`,
`F-054`, `F-058–F-062`, `F-064–F-066`, `F-070–F-072`, `F-074–F-079`, `F-081`,
`F-084`.

Недавние доказательные блоки: физически совместимый поиск `F-046` (`6f1853b`), параметрические
marketplace-модели `F-045` (`f0eb3eb`), developer API `F-066` (`393bfaa`), hole-pattern CAD
`F-024` (`0e61716`), scene-integrity `F-015` (`d88b7ce`, `b5167a5`), AR-export `F-026`
(`537ab23`) и два точных механизма `F-037/F-038` (`d51bdef`, `6655ece`).

## 2. Реализовано в честно ограниченной границе; нужна внешняя/физическая приёмка или более широкий продуктовый объём

| ID | Что реально есть | Что ещё нельзя объявлять завершённым |
|---|---|---|
| F-002 | Фото/scanner sessions, fusion, RoomPlan-модуль, room shell | Сборка Swift и приёмка на физическом LiDAR; StructureBuilder для нескольких реальных RoomPlan-сессий |
| F-012 | Game-ready GLB, LOD/UV/PBR/collider и настоящий rigid animation channel | Универсальный character auto-rig и prefab-проверка в Unity/Unreal |
| F-014/F-015 | Проверяемые открытые форматы, bounded ABC, scene/material/animation integrity, exact GLB self-check | Идеальный proprietary round-trip и приёмка во всех внешних DCC/CAD-пакетах |
| F-019 | Реальный opt-in Shap-E photo-to-mesh путь | Производительное выполнение модели на целевом GPU/оборудовании; одна фотография не даёт измеренную обратную сторону |
| F-020 | Калиброванное фото + подписанные размеры → точная CAD-деталь | Автономное CV-измерение произвольной сцены без измерительного референса |
| F-026 | Метрический USDZ после integrity gate и системная `rel=ar` Quick Look-ссылка | Физическая AR-приёмка на совместимом iPhone/iPad |
| F-028/F-029 | Профили принтера, калибровочные купоны и измеренные поправки в G-code | Печать и измерение купона на конкретном физическом принтере |
| F-033 | Bounded нагрузочная оценка и измеренное усиление | Сертификационная FEA/topology optimization не заявляется |
| F-037/F-038 | Точная шарнирная крышка и sliding lid; revolute/prismatic GLB-анимации | Прочность, износ, трение и посадка требуют печати; это не универсальный синтез любых механизмов |
| F-043/F-044 | Scan-vs-CAD deviation и запись измеренной коррекции профиля | Физический цикл печать → скан → повторная печать |
| F-050 | Линейка, себестоимость, цена, инструкции и canonical renders из сохранённых фактов | Будущий спрос не выдумывается; нужен внешний market signal |
| F-055 | Модульная geometry/material/printer/print-result архитектура и usage/provenance | Собственная универсальная Physical Manufacturing Model — долгосрочная модель, не отдельный endpoint |
| F-056 | Замкнутый цифровой цикл, diagnosis и OctoPrint adapter | Физический принтер/камера и production OctoPrint-среда |
| F-057 | Tauri shell для Windows/macOS | Подписанные production-сборки и приёмка на обеих ОС |
| F-063 | Стандартные 3MF/STL/G-code пути и профили популярных принтеров | Матрица импорта/печати в реальных Bambu/Prusa/Creality приложениях и устройствах |
| F-068 | Идемпотентный usage ledger и `/usage`; все 36 job-типов имеют versioned `2026-10-29.v1` credit quote, authenticated catalog/quote API и shadow snapshot без скрытого списания | Тарифы РФ/зарубежья, включённые кредиты, top-up/payment provider, возвраты и billing enforcement |
| F-069 | Очереди, лимиты, pause/cancel/retry и метрики | Production GPU provider/кластер и эксплуатационная приёмка |
| F-073 | Серверные immutable projects/assets и клиенты одной контрактной модели | Физический сценарий phone → desktop → web на разных устройствах |
| F-080 | Сквозные SEE→CREATE→TEST→PRINT→LEARN пути существуют по отдельным функциям | Это стратегическая оболочка Long-term, а не конечная бинарная функция |
| F-082 | Scanner bridge, folder/RealSense/simulation, metric fragments и fusion | Реальный scanner hardware acceptance |
| F-083 | Безопасные OTP/OAuth state/session adapters и demo providers | Реальные SMS/email, Yandex ID и VK ID операторы; stub запрещён в production |
| F-085 | Guided exterior capture, measured scale, resumable sections, COLMAP/reconstruction и semantic facade | Натурная съёмка здания целевым устройством и эксплуатационный compute budget |
| F-086 | Web и mobile имеют реальную topology, selection, grid/snap/symmetry, versioned mesh edits, dimensioned surface details, bounded planar/analytic multi-face recovery и mobile exact-CAD authoring через общий kernel-путь | Физическая touch/GPU-приёмка и универсальное восстановление произвольной freeform-топологии остаются более широкой границей |
| F-087 | Серверная mm-разметка плана, web/mobile tools, CAS/live sync, фото и 3D anchors | Физическая multi-device/touch приёмка и план из нескольких настоящих RoomPlan-сессий |

## 3. Нельзя честно завершить без решения владельца и внешней интеграции

| ID | Блокер | Требуемое решение/вход |
|---|---|---|
| F-048 Creator revenue sharing | Нет утверждённой формулы долей, получателей, удержаний, возвратов и налоговой модели; payment provider отсутствует | Правила revenue split + юридическая модель + production payout/payment provider |
| F-052 One-click manufacturing | Нет производственного партнёра, котировок, адресов доставки, SLA и оплаты | API/договор конкретного изготовителя, страны/валюты, shipping/tax правила |
| F-053 Distributed print network | Нет реестра исполнителей, зон, мощности, качества и маршрутизации заказов | Оператор сети, onboarding/SLA, география и dispatch API |
| F-067 Enterprise licensing | В коде есть роли workspace и Free/Pro entitlements, но нет утверждённых enterprise-планов, seats, SSO/SLA и биллинга | Тарифная/договорная матрица, identity/billing providers и требования к аудиту/retention |

Пока эти входы отсутствуют, production-конфигурация правильно работает fail-closed: stub-платежи,
stub-вход и stub-принтер запрещены; priced listings без провайдера возвращают контролируемый отказ;
кредиты не уменьшают баланс по выдуманной цене.

Итоговый счёт по главному ТЗ: **55** ID локально закрыты автоматическими доказательствами,
**28** имеют рабочую ограниченную границу и требуют физической/внешней приёмки либо более широкого
продуктового объёма, **4** заблокированы отсутствующим бизнес-решением и провайдером. Все 87 ID
учтены ровно один раз.

## Итоговая граница

В главном корпусе `F-001–F-087` не осталось полностью отсутствующего локального пути, который
можно честно «реализовать ещё раз» без дублирования. Следующий этап главного ТЗ — физическая
приёмка из раздела 2 либо предоставление решений/провайдеров для четырёх пунктов раздела 3.

В отдельной marketplace-матрице прежний локальный недублирующий разрыв M10 закрыт: publish wizard
добавляет поддерживаемый 3D-формат через существующий upload pipeline, а сервер привязывает
проверенный asset только как `export` к точной finalized version до первого submission. Версия,
уже использованная как anchor/component листинга, заморожена для операции, поэтому review нельзя
обойти заменой deliverables. Второй загрузчик и ослабление ACL не создавались. Checkout, seller
onboarding и выплаты не брать до выбора production payment/payout provider и бизнес-правил;
browser/device-приёмка M10 остаётся внешней проверкой, а не новым локальным endpoint-разрывом.
