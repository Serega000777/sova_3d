"""Versioned, read-only credit prices for successful platform jobs.

This catalogue is deliberately separate from payment and balance enforcement.  It gives every
registered job an honest quote while F-068 remains in shadow mode: completed jobs record the quote,
but no credits are debited until subscriptions, top-ups and refund rules are approved and wired to a
production payment provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

PRICING_VERSION = "2026-10-31.v1"
CHARGING_MODE = "shadow"

PricingCategory = Literal["ai", "scan", "cad", "edit", "verify", "print", "export"]
MarketCode = Literal["ru", "international"]
CurrencyCode = Literal["RUB", "USD"]


@dataclass(frozen=True, slots=True)
class ActionPrice:
    action_type: str
    category: PricingCategory
    credits: Decimal
    title_ru: str
    title_en: str


@dataclass(frozen=True, slots=True)
class SubscriptionOffer:
    code: str
    monthly_price_minor: int
    included_credits: int
    seats: int
    title_ru: str
    title_en: str


@dataclass(frozen=True, slots=True)
class CreditPack:
    code: str
    price_minor: int
    credits: int


@dataclass(frozen=True, slots=True)
class MarketOffers:
    market: MarketCode
    currency: CurrencyCode
    subscriptions: tuple[SubscriptionOffer, ...]
    credit_packs: tuple[CreditPack, ...]


def _price(
    action_type: str,
    category: PricingCategory,
    credits: int,
    title_ru: str,
    title_en: str,
) -> ActionPrice:
    return ActionPrice(action_type, category, Decimal(credits), title_ru, title_en)


# Prices are product credits, not provider invoices.  The relative ladder follows expected compute:
# deterministic metadata/preview jobs < exact geometry < vision/generative/reconstruction jobs.
# Provider-derived token/GPU cost remains separately attributable in the append-only usage ledger.
_ROWS = (
    _price("ai_command", "ai", 2, "Команда AI-дизайнеру", "AI designer command"),
    _price("analyze_print", "print", 2, "Анализ печати", "Print analysis"),
    _price("blender_handoff", "export", 3, "Пакет для Blender", "Blender handoff"),
    _price("auto_furnish_floor_plan", "cad", 4, "Автомеблировка плана", "Auto-furnish plan"),
    _price("build_enclosure", "cad", 4, "Параметрический корпус", "Parametric enclosure"),
    _price("build_hinged_lid", "cad", 5, "Шарнирная крышка", "Hinged lid"),
    _price("build_house_box", "cad", 4, "Объём дома", "House massing"),
    _price("build_house_walls", "cad", 6, "Точные стены дома", "Exact house walls"),
    _price("build_sliding_lid", "cad", 5, "Сдвижная крышка", "Sliding lid"),
    _price("compose_site_plan", "cad", 5, "Генплан участка", "Site plan composition"),
    _price("convert_asset", "export", 2, "Конвертация файла", "File conversion"),
    _price("demo_scan", "scan", 1, "Демонстрационный скан", "Demo scan"),
    _price("diagnose_print_photo", "ai", 6, "AI Print Doctor по фото", "AI Print Doctor photo"),
    _price("edit_facade", "edit", 4, "Правка фасада", "Facade edit"),
    _price("engineering_advice", "verify", 4, "Инженерная проверка", "Engineering check"),
    _price("execute_plan", "cad", 4, "Построение OperationPlan", "Build OperationPlan"),
    _price("export", "export", 2, "Экспорт модели", "Model export"),
    _price("extract_video_frames", "scan", 3, "Кадры из видео", "Extract video frames"),
    _price("fit_test", "verify", 4, "Проверка посадки", "Fit test"),
    _price("generate_mesh", "ai", 30, "AI-генерация 3D", "AI 3D generation"),
    _price("import_model", "export", 1, "Импорт модели", "Model import"),
    _price("inspect_assembly_geometry", "verify", 3, "Проверка сборки", "Assembly inspection"),
    _price("manual_edit", "edit", 1, "Точная ручная правка", "Exact manual edit"),
    _price("mesh_edit", "edit", 3, "Правка сетки", "Mesh edit"),
    _price("optimize_print", "print", 3, "Оптимизация печати", "Print optimization"),
    _price("paint_model", "ai", 12, "AI-текстурирование", "AI texturing"),
    _price("physical_compare", "verify", 8, "Сравнение скана с CAD", "Scan-to-CAD comparison"),
    _price("place_furniture", "edit", 1, "Расстановка мебели", "Furniture placement"),
    _price("reconstruct_scan", "scan", 40, "Реконструкция скана", "Scan reconstruction"),
    _price("remove_fragments", "edit", 3, "Удаление фрагментов", "Remove fragments"),
    _price("render_thumbnail", "export", 1, "Контрольный ракурс", "Reference thumbnail"),
    _price("repair", "verify", 4, "Ремонт геометрии", "Geometry repair"),
    _price("reverse_engineer", "cad", 12, "Mesh → параметрический CAD", "Mesh to parametric CAD"),
    _price("rollback", "edit", 1, "Восстановление версии", "Restore version"),
    _price("slice", "print", 8, "Полный слайсинг", "Full slicing"),
    _price("slice_preview", "print", 1, "Предпросмотр слайсинга", "Slice preview"),
    _price("split_model", "print", 6, "Деление под стол принтера", "Split for printer bed"),
)

CATALOGUE = {row.action_type: row for row in _ROWS}

# Commercial offers are published for product planning and client transparency. They are not
# purchasable while ``CHARGING_MODE`` is ``shadow``. Amounts use currency minor units (kopeks/
# cents), so clients never perform floating-point money arithmetic.
_PLAN_SHAPE = (
    ("free", False, 100, 1, "Бесплатный", "Free"),
    ("maker", True, 350, 1, "Мейкер", "Maker"),
    ("pro", True, 1500, 1, "Профи", "Pro"),
    ("studio", True, 5000, 1, "Студия", "Studio"),
    ("team", True, 15000, 5, "Команда", "Team"),
)


def _subscriptions(prices_minor: tuple[int, ...]) -> tuple[SubscriptionOffer, ...]:
    return tuple(
        SubscriptionOffer(
            code=code,
            monthly_price_minor=prices_minor[index] if priced else 0,
            included_credits=credits,
            seats=seats,
            title_ru=title_ru,
            title_en=title_en,
        )
        for index, (code, priced, credits, seats, title_ru, title_en) in enumerate(_PLAN_SHAPE)
    )


MARKETS = (
    MarketOffers(
        market="ru",
        currency="RUB",
        subscriptions=_subscriptions((0, 49_000, 149_000, 399_000, 999_000)),
        credit_packs=(
            CreditPack("credits_250", 39_000, 250),
            CreditPack("credits_1000", 129_000, 1000),
            CreditPack("credits_5000", 499_000, 5000),
        ),
    ),
    MarketOffers(
        market="international",
        currency="USD",
        subscriptions=_subscriptions((0, 799, 1999, 4999, 12900)),
        credit_packs=(
            CreditPack("credits_250", 499, 250),
            CreditPack("credits_1000", 1499, 1000),
            CreditPack("credits_5000", 4999, 5000),
        ),
    ),
)


def action_price(action_type: str) -> ActionPrice:
    """Return the canonical price, failing closed for an unpriced job type."""
    try:
        return CATALOGUE[action_type]
    except KeyError as exc:
        raise ValueError(f"unpriced action_type: {action_type}") from exc


def quote(action_type: str, quantity: int = 1) -> Decimal:
    if quantity < 1 or quantity > 1000:
        raise ValueError("quantity must be between 1 and 1000")
    return action_price(action_type).credits * quantity


def catalogue() -> tuple[ActionPrice, ...]:
    return tuple(sorted(_ROWS, key=lambda row: (row.category, row.action_type)))


def market_offers() -> tuple[MarketOffers, ...]:
    return MARKETS
