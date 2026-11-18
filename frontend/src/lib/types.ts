// Hand-written from backend/app/schemas.py (the API contract). Keep in sync.

// --- auth ----------------------------------------------------------------------

export interface StatusOut {
  version: string;
  /** A single-sign-on proxy signs people in, so the sign-in screen has nothing to ask for. */
  single_sign_on: boolean;
}

/** A Grocy username and password, or (the fallback) just a Grocy API key. */
export interface LoginIn {
  username?: string | null;
  password?: string | null;
  api_key?: string | null;
}

export interface UserOut {
  id: number;
  /** Grocy username */
  username: string;
  /** Grocy display name; falls back to the username */
  display_name: string;
  /** Holds Grocy's ADMIN permission */
  is_admin: boolean;
  /**
   * The single-sign-on proxy is what has them signed in right now, so signing out
   * here would be undone by the next request. Only `/auth/me` says.
   */
  via_proxy?: boolean;
}

// --- settings ----------------------------------------------------------------

export type AIProviderName = 'none' | 'anthropic' | 'openai';
export type AIMode = 'fallback' | 'always';

export interface AISettingsOut {
  provider: AIProviderName;
  model: string | null;
  base_url: string | null;
  mode: AIMode;
  api_key_set: boolean;
}

/** Partial update; omitted fields are left alone. api_key "" clears the key. */
export interface AISettingsIn {
  provider?: AIProviderName | null;
  model?: string | null;
  base_url?: string | null;
  mode?: AIMode | null;
  api_key?: string | null;
}

/** Which AI settings an endpoint is about: one person's own, or the household default. */
export type AIScope = 'personal' | 'instance';

export interface SettingsOut {
  /** This person's own override; provider "none" means "use the household default". */
  personal_ai: AISettingsOut;
  /** The household default; null unless the caller is an admin. */
  instance_ai: AISettingsOut | null;
  /** Which of the two this person's receipts will actually use. */
  ai_source: 'personal' | 'instance' | 'none';
}

export interface TestResult {
  ok: boolean;
  message: string;
}

// --- Grocy master data ---------------------------------------------------------

export interface IdName {
  id: number;
  name: string;
}

export interface QuantityUnit extends IdName {
  name_plural: string;
}

export interface NewProductDraft {
  name: string;
  location_id: number;
  qu_id: number;
  product_group_id?: number | null;
  /** 0 / -1 = never overdue */
  default_best_before_days?: number;
  /** Sold in packs: one `pack_qu_id` holds `pack_size` of `qu_id` (1 Pack = 24 Pieces). */
  pack_size?: number | null;
  pack_qu_id?: number | null;
}

export interface NewProductDefaults {
  location_id: number | null;
  qu_id: number | null;
  product_group_id: number | null;
  default_best_before_days: number;
}

export interface GrocyMeta {
  grocy_version: string | null;
  locations: IdName[];
  stores: IdName[];
  quantity_units: QuantityUnit[];
  product_groups: IdName[];
  new_product_defaults: NewProductDefaults;
  /** False when this is the server's saved copy because Grocy couldn't be reached. */
  grocy_reachable: boolean;
}

export interface ProductHit {
  id: number;
  name: string;
  score?: number | null;
}

// --- trips -------------------------------------------------------------------

export type ItemState = 'needs_product' | 'ready' | 'committed' | 'failed' | 'skipped';

export interface LookupOut {
  found: boolean;
  name: string;
  brand: string;
  quantity: string;
  image_url: string | null;
  source: string | null;
  suggested_name: string;
}

export interface ItemOut {
  id: number;
  source: 'scan' | 'receipt' | 'manual';
  barcode: string | null;
  scan_count: number;
  state: ItemState;
  name: string;

  product: IdName | null;
  link_barcode: boolean;
  new_product: NewProductDraft | null;
  lookup: LookupOut | null;
  suggestions: ProductHit[];

  quantity: number;
  quantity_source: 'manual' | 'receipt' | 'scans' | 'default';
  pack_factor: number;
  pack_unit: string;
  stock_amount: number;
  stock_unit: string;

  line_total: number | null;
  price_source: 'manual' | 'receipt' | null;
  unit_price: number | null;

  due_date: string; // ISO date or "never"
  due_source: 'manual' | 'default';
  location_id: number | null;
  shopping_location_id: number | null;
  note: string | null;

  receipt_line_id: number | null;
  match_score: number | null;
  match_method: 'upc' | 'learned' | 'fuzzy' | 'ai' | 'manual' | null;

  warnings: string[];
  error: string | null;
  committed_amount: number | null;
}

export interface ItemCreate {
  product_id: number;
  quantity?: number | null;
}

/**
 * Partial update. A key that is present with value null clears that override
 * (the value is derived again). Omitted keys are untouched.
 */
export interface ItemPatch {
  product_id?: number | null;
  new_product?: NewProductDraft | null;
  quantity?: number | null;
  line_total?: number | null;
  due_date?: string | null;
  location_id?: number | null;
  shopping_location_id?: number | null;
  note?: string | null;
  receipt_line_id?: number | null;
  skipped?: boolean | null;
}

export interface ScanOut {
  item: ItemOut;
  duplicate: boolean;
}

export interface ReceiptImageOut {
  id: number;
  url: string;
}

export interface ReceiptLineOut {
  id: number;
  receipt_id: number;
  position: number;
  description: string;
  raw_text: string;
  item_code: string | null;
  quantity: number;
  unit_price: number | null;
  total_price: number | null;
  discount: number | null;
  weight: number | null;
  weight_unit: string | null;
  dismissed: boolean;
  matched_item_id: number | null;
  suggested_product: IdName | null;
}

export interface ReceiptOut {
  id: number;
  status: 'processing' | 'ready' | 'failed';
  store_key: string | null;
  store_name: string | null;
  shopping_location_id: number | null;
  purchased_on: string | null;
  subtotal: number | null;
  tax: number | null;
  total: number | null;
  method: 'ocr' | 'ai' | null;
  confidence: number | null;
  warnings: string[];
  error: string | null;
  images: ReceiptImageOut[];
  lines: ReceiptLineOut[];
}

export interface ReceiptPatch {
  shopping_location_id?: number | null;
  purchased_on?: string | null;
  store_name?: string | null;
}

export interface LinePatch {
  description?: string | null;
  quantity?: number | null;
  total_price?: number | null;
  dismissed?: boolean | null;
}

export interface LineItemCreate {
  product_id?: number | null;
  new_product?: NewProductDraft | null;
}

export interface TripSummary {
  id: number;
  name: string;
  status: 'open' | 'submitted';
  created_at: string;
  submitted_at: string | null;
  created_by: string;
  item_count: number;
  receipt_count: number;
  stores: string[];
  total: number | null;
  /** Goes up on every change to the trip, from any device. */
  revision: number;
}

export interface TripOut extends TripSummary {
  items: ItemOut[];
  receipts: ReceiptOut[];
  processing: boolean;
  ready_count: number;
  attention_count: number;
  ai_available: boolean;
  /** False when the server answered from its saved copy of Grocy's data because Grocy couldn't be reached. */
  grocy_reachable: boolean;
}

export interface SubmitResult {
  committed: number;
  failed: number;
  remaining: number;
  trip: TripOut;
}
