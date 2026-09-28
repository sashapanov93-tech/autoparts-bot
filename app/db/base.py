from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import Base

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    from sqlalchemy import select

    from app.db.models import Product, ProductPhoto

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Миграция legacy: одиночное photo_id -> product_photos
    async with SessionFactory() as session:
        stmt = select(Product).where(Product.photo_id.is_not(None))
        for p in (await session.execute(stmt)).scalars().all():
            has = (await session.execute(
                select(ProductPhoto.id).where(ProductPhoto.product_id == p.id).limit(1)
            )).first()
            if not has:
                session.add(ProductPhoto(product_id=p.id, file_id=p.photo_id, position=0))
        await session.commit()
