"""The local catalogue showcase uses real domain records and is safe to rerun."""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.marketplace import CreatorProfile, MarketplaceItem, MarketplaceItemComponent
from app.models.versioning import AssetRole, VersionAsset
from app.services.marketplace_showcase import PRODUCTS, seed_marketplace_showcase
from app.storage import S3Storage


def test_showcase_is_real_idempotent_marketplace_data(
    db_session: Session, storage: S3Storage
) -> None:
    first = seed_marketplace_showcase(db_session, storage, app_env="local")
    second = seed_marketplace_showcase(db_session, storage, app_env="dev")

    assert first.listings == len(PRODUCTS)
    assert first.created_listings == len(PRODUCTS)
    assert second.created_listings == 0
    listings = db_session.scalars(
        sa.select(MarketplaceItem).where(
            MarketplaceItem.title.in_([product.title for product in PRODUCTS])
        )
    ).all()
    assert len(listings) == len(PRODUCTS)
    assert {item.price_cents == 0 for item in listings} == {True, False}
    assert len({item.creator_user_id for item in listings}) == 3
    assert db_session.scalar(sa.select(sa.func.count()).select_from(CreatorProfile)) == 3
    assert (
        db_session.scalar(sa.select(sa.func.count()).select_from(MarketplaceItemComponent)) == 2
    )
    for item in listings:
        roles = set(
            db_session.scalars(
                sa.select(VersionAsset.role).where(VersionAsset.version_id == item.version_id)
            )
        )
        assert {AssetRole.model, AssetRole.thumbnail} <= roles


def test_showcase_refuses_production(db_session: Session, storage: S3Storage) -> None:
    try:
        seed_marketplace_showcase(db_session, storage, app_env="production")
    except ValueError as exc:
        assert str(exc) == "marketplace showcase seed is forbidden in production"
    else:
        raise AssertionError("production seed was accepted")
