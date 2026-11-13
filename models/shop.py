from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

KIND_SHOP = "shop"

DELIVERY, PICKUP = "delivery", "pickup"
PAY_CASH, PAY_CARD = "cash", "card"
PAID_NO, PAID_PENDING, PAID_YES, PAID_REJECTED = "unpaid", "pending", "paid", "rejected"
ST_NEW, ST_CONFIRMED, ST_PREPARING, ST_SHIPPING, ST_DONE, ST_CANCELLED = (
    "new", "confirmed", "preparing", "shipping", "done", "cancelled")
ACTIVE_STATUSES = (ST_NEW, ST_CONFIRMED, ST_PREPARING, ST_SHIPPING)


class ShopSettings(Base):
    """One row per shop bot."""
    __tablename__ = "shop_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), unique=True, nullable=False)
    card_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    card_holder: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pay_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cash_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    card_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    delivery_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    pickup_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    delivery_fee: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    free_delivery_from: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    min_order: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)


class ShopCategory(Base):
    __tablename__ = "shop_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)


class ShopProduct(Base):
    __tablename__ = "shop_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("shop_categories.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    old_price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # shown crossed out when higher than price
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = unlimited (ignored when variants exist)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ShopImage(Base):
    __tablename__ = "shop_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("shop_products.id", ondelete="CASCADE"), index=True, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    file_id: Mapped[str] = mapped_column(String(255), nullable=False)


class ShopVariant(Base):
    __tablename__ = "shop_variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("shop_products.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    price: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # None = the product's price
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class CartItem(Base):
    __tablename__ = "shop_cart_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("shop_products.id", ondelete="CASCADE"), nullable=False)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("shop_variants.id", ondelete="CASCADE"), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Order(Base):
    __tablename__ = "shop_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id"), index=True, nullable=False)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    user_name: Mapped[str] = mapped_column(String(120), default="", server_default="", nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phone: Mapped[str] = mapped_column(String(32), default="", server_default="", nullable=False)
    delivery_type: Mapped[str] = mapped_column(String(10), default=PICKUP, server_default=PICKUP, nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_method: Mapped[str] = mapped_column(String(10), default=PAY_CASH, server_default=PAY_CASH, nullable=False)
    payment_status: Mapped[str] = mapped_column(String(10), default=PAID_NO, server_default=PAID_NO, nullable=False)
    receipt_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    subtotal: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    delivery_fee: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    total: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0", nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=ST_NEW, server_default=ST_NEW, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrderItem(Base):
    """Snapshot of a cart line: later product edits or deletion do not change old orders."""
    __tablename__ = "shop_order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("shop_orders.id", ondelete="CASCADE"), index=True, nullable=False)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("shop_products.id", ondelete="SET NULL"), nullable=True)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("shop_variants.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
