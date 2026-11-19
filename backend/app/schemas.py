"""Request/response models. This file is the API contract the PWA is built against."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# --- sign-in ----------------------------------------------------------------


class StatusOut(BaseModel):
    version: str
    # A single-sign-on proxy signs people in (GA_TRUSTED_USER_HEADER), so the
    # sign-in screen has nothing to ask for.
    single_sign_on: bool = False


class LoginIn(BaseModel):
    """Grocy username + password, or (fallback) just a Grocy API key."""

    username: str | None = None
    password: str | None = None
    api_key: str | None = None


class UserOut(BaseModel):
    id: int  # app user id
    username: str  # Grocy username
    display_name: str  # Grocy display name, falling back to the username
    is_admin: bool  # holds Grocy's ADMIN permission


class MeOut(UserOut):
    # The single-sign-on proxy is what has them signed in right now. Signing out
    # here would be undone by their next request; they sign out at the proxy.
    via_proxy: bool = False


# --- settings --------------------------------------------------------------

AIProviderName = Literal["none", "anthropic", "openai"]
AIMode = Literal["fallback", "always"]


class AISettingsOut(BaseModel):
    provider: AIProviderName
    model: str | None
    base_url: str | None
    mode: AIMode  # fallback: only when OCR/matching is unsure; always: read every receipt
    api_key_set: bool


class AISettingsIn(BaseModel):
    """Partial update; omitted fields are left alone. api_key="" clears the key."""

    provider: AIProviderName | None = None
    model: str | None = None
    base_url: str | None = None
    mode: AIMode | None = None
    api_key: str | None = None


class SettingsOut(BaseModel):
    # This user's own override; provider "none" = use the household default.
    personal_ai: AISettingsOut
    # The household default; null unless the caller is an admin.
    instance_ai: AISettingsOut | None
    # Which of the two this user's receipts will actually use.
    ai_source: Literal["personal", "instance", "none"]


class TestResult(BaseModel):
    ok: bool
    message: str


# --- Grocy master data -----------------------------------------------------


class IdName(BaseModel):
    id: int
    name: str


class QuantityUnit(IdName):
    name_plural: str


class NewProductDraft(BaseModel):
    """Everything needed to create a product in Grocy at submit time."""

    name: str = Field(min_length=1, max_length=200)
    location_id: int
    qu_id: int  # stock and consume unit (also purchase and price unit, unless sold in packs)
    product_group_id: int | None = None
    default_best_before_days: int = 0  # 0 / -1 = never overdue
    # Sold in packs: one `pack_qu_id` holds `pack_size` of `qu_id` (e.g. 1 Pack = 24 Pieces).
    # Becomes the purchase and price unit, a conversion, and the barcode's unit.
    pack_size: float | None = Field(default=None, gt=0, le=100000)
    pack_qu_id: int | None = None


class NewProductDefaults(BaseModel):
    location_id: int | None
    qu_id: int | None
    product_group_id: int | None
    default_best_before_days: int


class GrocyMeta(BaseModel):
    grocy_version: str | None
    locations: list[IdName]
    stores: list[IdName]
    quantity_units: list[QuantityUnit]
    product_groups: list[IdName]
    new_product_defaults: NewProductDefaults
    # False when this was built from an old snapshot because Grocy couldn't be reached.
    grocy_reachable: bool


class ProductHit(BaseModel):
    id: int
    name: str
    score: float | None = None


class StoreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


# --- trips -----------------------------------------------------------------

ItemState = Literal["needs_product", "ready", "committed", "failed", "skipped"]
TripKind = Literal["shopping", "inventory"]


class Lot(BaseModel):
    """Part of an item's quantity with a due date of its own (e.g. 2 of the 5 cans
    are due in March). Amounts are in the same unit as the item's `quantity`."""

    amount: float = Field(gt=0, le=100000)
    due_date: str  # ISO date or "never"


class LookupOut(BaseModel):
    found: bool
    name: str = ""
    brand: str = ""
    quantity: str = ""
    image_url: str | None = None
    source: str | None = None
    suggested_name: str = ""


class ItemOut(BaseModel):
    id: int
    source: Literal["scan", "receipt", "manual"]
    barcode: str | None
    scan_count: int
    state: ItemState
    # Best available display name (Grocy product, draft, lookup, or the barcode).
    name: str

    # Product resolution
    product: IdName | None  # existing Grocy product
    link_barcode: bool  # barcode will be attached to `product` at submit
    new_product: NewProductDraft | None  # confirmed draft, created at submit
    lookup: LookupOut | None  # external barcode lookup result for unknown barcodes
    suggestions: list[ProductHit]  # similar existing products, for unresolved items

    # Quantity: `quantity` packs as bought, each worth `pack_factor` stock units.
    quantity: float
    quantity_source: Literal["manual", "receipt", "scans", "default"]
    pack_factor: float
    pack_unit: str  # e.g. "Pack"
    stock_amount: float  # what will be added to Grocy
    stock_unit: str  # e.g. "Pieces"

    # Price: total paid for this item, and the derived per-stock-unit price sent to Grocy.
    line_total: float | None
    price_source: Literal["manual", "receipt"] | None
    unit_price: float | None

    # Parts of the quantity with their own due dates. What they leave over
    # (`rest_amount`) is due on `due_date`, which is the product's default unless set.
    lots: list[Lot]
    rest_amount: float
    due_date: str  # ISO date or "never"
    due_source: Literal["manual", "default"]
    location_id: int | None
    shopping_location_id: int | None
    note: str | None

    # Receipt match
    receipt_line_id: int | None
    match_score: float | None
    match_method: Literal["upc", "learned", "fuzzy", "ai", "manual"] | None

    # How much of the product Grocy has in stock right now (in `stock_unit`), for
    # products that already exist; null when unknown.
    in_stock: float | None
    warnings: list[str]
    error: str | None  # set when state == "failed"
    committed_amount: float | None


class ItemCreate(BaseModel):
    """Add an item without scanning (no barcode on the package)."""

    product_id: int
    quantity: float | None = Field(default=None, gt=0)


class ItemPatch(BaseModel):
    """Partial update. A field that is present but null clears that override, so the
    value is derived again (receipt line / Grocy defaults).

    Product resolution: send `product_id` to link an existing product, or
    `new_product` to confirm creating one. Sending either clears the other."""

    product_id: int | None = None
    new_product: NewProductDraft | None = None
    quantity: float | None = Field(default=None, gt=0)
    line_total: float | None = Field(default=None, ge=0)
    due_date: str | None = None  # ISO date or "never"
    # Replaces the item's lots; [] or null removes them. If they add up to more than the
    # quantity, the quantity goes up to match.
    lots: list[Lot] | None = Field(default=None, max_length=100)
    location_id: int | None = None
    shopping_location_id: int | None = None
    note: str | None = None
    receipt_line_id: int | None = None  # manual match; null unmatches
    skipped: bool | None = None


class BulkItemPatch(BaseModel):
    """The same change to several items at once (the bulk-edit table). Fields work as
    in ItemPatch: present-but-null goes back to the derived value."""

    item_ids: list[int] = Field(min_length=1, max_length=500)
    due_date: str | None = None
    location_id: int | None = None
    shopping_location_id: int | None = None
    skipped: bool | None = None


class ScanIn(BaseModel):
    barcode: str = Field(min_length=1, max_length=128)


class ScanOut(BaseModel):
    item: ItemOut
    duplicate: bool  # barcode was already in this trip; its scan_count was bumped


class ReceiptImageOut(BaseModel):
    id: int
    url: str


class ReceiptLineOut(BaseModel):
    id: int
    receipt_id: int
    position: int
    description: str
    raw_text: str
    item_code: str | None
    quantity: float
    unit_price: float | None
    total_price: float | None
    discount: float | None
    weight: float | None
    weight_unit: str | None
    dismissed: bool
    matched_item_id: int | None
    # A product this line mapped to on a previous trip (for lines without a scan).
    suggested_product: IdName | None


class ReceiptOut(BaseModel):
    id: int
    status: Literal["processing", "ready", "failed"]
    store_key: str | None
    store_name: str | None
    shopping_location_id: int | None
    purchased_on: str | None
    subtotal: float | None
    tax: float | None
    total: float | None
    method: Literal["ocr", "ai"] | None
    confidence: float | None
    warnings: list[str]
    error: str | None
    images: list[ReceiptImageOut]
    lines: list[ReceiptLineOut]


class ReceiptPatch(BaseModel):
    """Present-but-null clears. Setting shopping_location_id is remembered per store."""

    shopping_location_id: int | None = None
    purchased_on: str | None = None
    store_name: str | None = None


class ReprocessIn(BaseModel):
    use_ai: bool = False  # force an AI read even if OCR was confident


class LinePatch(BaseModel):
    description: str | None = None
    quantity: float | None = Field(default=None, gt=0)
    total_price: float | None = Field(default=None, ge=0)
    dismissed: bool | None = None


class LineItemCreate(BaseModel):
    """Turn a receipt line with no scanned barcode (produce, deli) into an item."""

    product_id: int | None = None
    new_product: NewProductDraft | None = None


class TripCreate(BaseModel):
    name: str = Field(default="", max_length=120)
    kind: TripKind = "shopping"


class TripPatch(BaseModel):
    name: str = Field(max_length=120)


class TripSummary(BaseModel):
    id: int
    name: str
    kind: TripKind
    status: Literal["open", "submitted"]
    created_at: datetime
    submitted_at: datetime | None
    created_by: str
    item_count: int
    committed_count: int  # items already booked into Grocy
    receipt_count: int
    stores: list[str]
    total: float | None  # sum of receipt totals when known
    # Increases on every change to the trip; compare with GET /trips/{id}/revision.
    revision: int


class TripOut(TripSummary):
    items: list[ItemOut]
    receipts: list[ReceiptOut]
    processing: bool  # a receipt is still being read; poll again shortly
    ready_count: int
    attention_count: int  # items that need a product decision before they can be added
    ai_available: bool  # the signed-in user has an AI provider (their own or the household's)
    # False when this was built from an old snapshot because Grocy couldn't be reached.
    grocy_reachable: bool


class RevisionOut(BaseModel):
    revision: int


class SubmitResult(BaseModel):
    committed: int
    failed: int
    remaining: int  # items still pending (need a product) after this submit
    trip: TripOut


# --- consuming and opening stock ----------------------------------------------


class StockProduct(BaseModel):
    """A product as it stands in Grocy right now, for consuming or opening some of it.
    Amounts are in the product's stock unit."""

    id: int
    name: str
    amount: float  # in stock (with sub-products, for a parent product)
    amount_opened: float
    unit: str  # stock unit, singular ("Piece")
    unit_plural: str  # "Pieces"
    next_due_date: str | None  # ISO date, "never", or null when nothing is in stock
    location: str | None  # the product's default location
    # What one tap consumes or opens by default (Grocy's "quick consume/open amount").
    quick_consume_amount: float
    quick_open_amount: float
    # Whether fractional amounts make sense (Grocy's "allow partial units in stock").
    allow_partial: bool
    # The scanned barcode stands for this much (a pack of 6, say); null otherwise.
    pack_amount: float | None = None
    # A Grocycode label of one particular stock entry: only that entry is used.
    stock_entry_id: str | None = None
    # Products whose containers are weighed (tare handling) are left to Grocy.
    tare_weight_handling: bool = False


class StockScanIn(BaseModel):
    barcode: str = Field(min_length=1, max_length=128)


class StockActionIn(BaseModel):
    amount: float = Field(gt=0, le=100000)
    stock_entry_id: str | None = Field(default=None, max_length=64)
    spoiled: bool = False  # consume only: it was thrown out, not eaten


class StockActionOut(BaseModel):
    # Grocy's transaction, for undoing this action.
    transaction_id: str | None
    product: StockProduct  # the product after the action


class StockUndoIn(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=64)
