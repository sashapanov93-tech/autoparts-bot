from datetime import datetime
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # telegram_id
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    emoji: Mapped[str] = mapped_column(String(16), default="🔧")

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article: Mapped[str] = mapped_column(String(64), unique=True)  # артикул
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2))
    stock: Mapped[int] = mapped_column(Integer, default=0)
    photo_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # legacy: 1-е фото
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    category: Mapped[Category | None] = relationship(back_populates="products")
    photos: Mapped[list["ProductPhoto"]] = relationship(
        back_populates="product", cascade="all, delete-orphan",
        order_by="ProductPhoto.position")


class ProductPhoto(Base):
    """Фото товара, до 3 шт., порядок — position."""
    __tablename__ = "product_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    file_id: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)

    product: Mapped[Product] = relationship(back_populates="photos")


class CartItem(Base):
    __tablename__ = "cart_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[int] = mapped_column(Integer, default=1)


class VehicleMake(Base):
    """Марка авто: Toyota, Kia, ..."""
    __tablename__ = "vehicle_makes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)

    models: Mapped[list["VehicleModel"]] = relationship(back_populates="make", cascade="all, delete-orphan")


class VehicleModel(Base):
    """Модель авто: Camry, Rio, ..."""
    __tablename__ = "vehicle_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    make_id: Mapped[int] = mapped_column(ForeignKey("vehicle_makes.id"))
    name: Mapped[str] = mapped_column(String(80))

    make: Mapped[VehicleMake] = relationship(back_populates="models")


class Fitment(Base):
    """Применимость товара к авто: товар подходит для make/model/годы."""
    __tablename__ = "fitments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    make_id: Mapped[int] = mapped_column(ForeignKey("vehicle_makes.id"))
    model_id: Mapped[int] = mapped_column(ForeignKey("vehicle_models.id"))
    year_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_to: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SelectionRequest(Base):
    """Заявка на подбор: по VIN / по фото / по марка-модель-год."""
    __tablename__ = "selection_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16), default="vin")  # vin/photo/mmy
    vin: Mapped[str | None] = mapped_column(String(17), nullable=True)
    photo_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    make: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)  # что ищет
    status: Mapped[str] = mapped_column(String(16), default="new")  # new/answered/closed
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(32), default="new")  # new/processing/done/cancelled
    total: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    contact: Mapped[str] = mapped_column(String(255), default="")
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    price: Mapped[float] = mapped_column(Numeric(12, 2))

    order: Mapped[Order] = relationship(back_populates="items")
