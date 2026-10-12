# Комната без LiDAR: bounded photo-room scan

Status: bounded реализация завершена 13.10.2026; physical camera acceptance остаётся открытым.

## Проверенный разрыв

Mobile уже позволяет выбрать «Фотокадры» для комнаты, но этот путь создаёт обычный RGB scan.
Job направляет его в object provider (`stub` или single-photo Shap-E), не требует покрытия стен и
при отсутствии подсказки присваивает условные 100 мм. Поэтому существующий экран нельзя считать
сканированием комнаты без LiDAR.

## Первый ограниченный инкремент

Поддерживается одна комната, снятая четырьмя последовательными проходами: стена 1, 2, 3 и 4.
Каждый проход требует не менее восьми перекрывающихся RGB-кадров. Перед обработкой пользователь
вводит измеренный максимальный горизонтальный пролёт комнаты в диапазоне 1–100 000 мм. Это scale-assist,
а не измерение камеры; результат и review показывают источник масштаба и среднюю уверенность.

Сервер не доверяет capture stats: он проверяет секцию каждого сохранённого кадра, минимум по всем
четырём секциям, наличие orientation metadata и bounded положительный размер. Confidence
фиксируется сервером на 0.6 и не может быть повышен клиентом. Worker запускает тот же
изолированный COLMAP SfM/Delaunay stack, который уже доказан для фасада, но с отдельным
`colmap_room` provider/provenance. Все четыре секции должны войти в один camera solution и каждая
должна сохранить не менее трёх зарегистрированных кадров. Полученный mesh выравнивается по
средним направлениям секций, масштабируется по максимальному extent, получает photo texture и
проходит общие repair/decimation/version gates.

## Fail-closed границы

- Нет измеренного максимального пролёта — finalize отклоняется.
- Нет 8 кадров любой стены, orientation metadata или единого COLMAP solution — job не создаёт
  правдоподобную заглушку.
- `stub` и Shap-E никогда не используются для `room_photogrammetry_v1`.
- COLMAP-путь не имеет durable texture checkpoint: running job нельзя объявлять paused.
- Исторические generic room RGB sessions не переинтерпретируются задним числом.

## Не входит

Автоматическое выделение стен/окон, точный 2D floor plan, RoomPlan-like semantic shell, комнаты с
более чем четырьмя стенами, объединение этажей/комнат, AR/depth scale и гарантированная
строительная точность. Для них нужны отдельные increments. Physical camera walk-through остаётся
обязательным acceptance gate после Linux/fixture проверок.

## Проверки

- API: section/pose/scale validation, provider selection, authorization и integration job.
- Worker: валидный room manifest/result, missing/disconnected/forged section failures, texture.
- Mobile/contracts: typecheck, capture metadata и UI state; production iOS export.
- Полные API/worker/contracts/web/monorepo gates, ledger, review, commit и push.
