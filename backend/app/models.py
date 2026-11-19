"""SQLite persistence. Grocy stays the source of truth for products and stock;
this database only holds who has signed in (and their Grocy API key), in-progress
shopping trips, and what the matcher has learned about how each store prints its
receipts."""

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, event
from sqlalchemy import UniqueConstraint as Unique
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime | None) -> datetime | None:
    """SQLite hands datetimes back without their timezone; they are stored as UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class User(Base):
    """Someone who has signed in with their Grocy account. There are no local
    passwords: the row is created on first sign-in and keyed by Grocy's user id."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    grocy_user_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    # Refreshed from Grocy on every sign-in.
    username: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255), default="")
    # Mirrors Grocy's ADMIN permission; re-checked when admin_checked_at gets old.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    admin_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Fernet-encrypted personal Grocy API key; purchases are booked under it.
    grocy_api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Personal AI provider, overriding the household default. "none" = use the default.
    ai_provider: Mapped[str] = mapped_column(String(16), default="none")
    ai_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ai_base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ai_mode: Mapped[str] = mapped_column(String(16), default="fallback")
    ai_api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Set when the app ended this session itself (Grocy stopped accepting the
    # account). The row is kept so every device still holding the cookie can be
    # told why it was signed out, instead of just "not signed in".
    ended_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    user: Mapped[User] = relationship()


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[object] = mapped_column(JSON)


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120), default="")
    # shopping: things just bought (purchases, usually with a receipt).
    # inventory: counting what is already in the house (inventory corrections, no receipt).
    kind: Mapped[str] = mapped_column(String(16), default="shopping", server_default="shopping")
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | submitted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Goes up whenever anything in the trip changes (see _bump_revisions below), so
    # another device showing the same trip can cheaply ask "is my copy stale?".
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    user: Mapped[User] = relationship()
    items: Mapped[list["TripItem"]] = relationship(
        back_populates="trip", cascade="all, delete-orphan", order_by="TripItem.id"
    )
    receipts: Mapped[list["Receipt"]] = relationship(
        back_populates="trip", cascade="all, delete-orphan", order_by="Receipt.id"
    )


class TripItem(Base):
    __tablename__ = "trip_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16), default="scan")  # scan | receipt | manual
    barcode: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scan_count: Mapped[int] = mapped_column(Integer, default=1)

    # Product resolution. Exactly one of these ends up driving the submit:
    #   product_id                -> existing Grocy product
    #   product_id + link_barcode -> existing product, barcode gets attached to it
    #   new_product               -> confirmed draft, product is created at submit
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    link_barcode: Mapped[bool] = mapped_column(Boolean, default=False)
    new_product: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    lookup: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Manual overrides. None means "derive it" (receipt line, Grocy defaults).
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    line_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    due_date: Mapped[str | None] = mapped_column(String(10), nullable=True)  # ISO | "never"
    # Some of the quantity has its own due date: [{"amount": 2, "due_date": "2026-12-01"}],
    # amounts in the same unit as `quantity`. Whatever they leave over uses `due_date`.
    lots: Mapped[list | None] = mapped_column(JSON, nullable=True)
    location_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shopping_location_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    receipt_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("receipt_lines.id", ondelete="SET NULL"), nullable=True
    )
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # upc | learned | fuzzy | ai | manual
    match_method: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # pending | committed | failed | skipped
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Every Grocy booking made for this item (one per due date), recorded as each is
    # made. Non-empty on an item that isn't committed means a booking that couldn't be
    # rolled back yet; the next submit or undo takes it back out first.
    transaction_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    committed_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    trip: Mapped[Trip] = relationship(back_populates="items")
    receipt_line: Mapped["ReceiptLine | None"] = relationship()


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="processing")  # | ready | failed
    store_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    store_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    shopping_location_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purchased_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    subtotal: Mapped[float | None] = mapped_column(Float, nullable=True)
    tax: Mapped[float | None] = mapped_column(Float, nullable=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    method: Mapped[str | None] = mapped_column(String(8), nullable=True)  # ocr | ai
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    trip: Mapped[Trip] = relationship(back_populates="receipts")
    images: Mapped[list["ReceiptImage"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", order_by="ReceiptImage.position"
    )
    lines: Mapped[list["ReceiptLine"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", order_by="ReceiptLine.position"
    )


class ReceiptImage(Base):
    __tablename__ = "receipt_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(64), default="image/jpeg")

    receipt: Mapped[Receipt] = relationship(back_populates="images")


class ReceiptLine(Base):
    __tablename__ = "receipt_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(String(255), default="")
    item_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=1)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # What was actually paid for the line, discounts applied, tax excluded.
    total_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # The user said "this line isn't something I track in Grocy" (bags, deposits...).
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)

    receipt: Mapped[Receipt] = relationship(back_populates="lines")


class LearnedMapping(Base):
    """Remembers that a store's receipt code/text means a particular Grocy product."""

    __tablename__ = "learned_mappings"
    __table_args__ = (Unique("store_key", "kind", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    store_key: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(8))  # code | text
    key: Mapped[str] = mapped_column(String(255))
    product_id: Mapped[int] = mapped_column(Integer)
    hits: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class StoreMapping(Base):
    """Remembers which Grocy store a receipt's detected store corresponds to."""

    __tablename__ = "store_mappings"

    store_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    shopping_location_id: Mapped[int] = mapped_column(Integer)


def _owning_trip(obj: object) -> Trip | None:
    if isinstance(obj, Trip):
        return obj
    if isinstance(obj, TripItem | Receipt):
        return obj.trip
    if isinstance(obj, ReceiptLine | ReceiptImage):
        return obj.receipt.trip if obj.receipt is not None else None
    return None


@event.listens_for(Session, "before_flush")
def _bump_revisions(session: Session, _context, _instances) -> None:
    """Bump Trip.revision for every trip touched by this flush.

    Doing it here rather than in each endpoint means no code path that changes a
    trip (requests, background receipt reads, future features) can forget to.
    Rows removed from a trip's collections count too: that marks the parent dirty.
    """
    trips: dict[int, Trip] = {}
    changed = [*session.new, *(o for o in session.dirty if session.is_modified(o))]
    for obj in changed:
        trip = _owning_trip(obj)
        if trip is not None and trip not in session.deleted:
            trips[id(trip)] = trip
    for trip in trips.values():
        trip.revision = (trip.revision or 0) + 1
