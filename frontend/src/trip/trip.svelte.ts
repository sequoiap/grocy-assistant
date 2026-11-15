// State for one open trip page. Every mutation answers with the whole trip,
// which simply replaces local state; scans merge a single item for speed.
import { api, ApiError, errorMessage, isGrocyUnreachable } from '../lib/api';
import { meta } from '../lib/session.svelte';
import { reportError, toasts } from '../lib/ui.svelte';
import type { ItemOut, ReceiptLineOut, ReceiptOut, SubmitResult, TripOut } from '../lib/types';

// How often an open trip asks the server whether another device changed it.
const POLL_MS = 2000;
const POLL_BUSY_MS = 1200; // a receipt is being read: its result is due any moment
// Don't swap the page out from under someone who is mid-edit.
const TYPING_GRACE_MS = 4000;
// While Grocy is unreachable, how often to ask for the whole trip again to see
// whether it's back (the change counter doesn't move when Grocy returns).
const GROCY_RECHECK_MS = 15000;

export class TripStore {
  readonly id: number;
  trip = $state<TripOut | null>(null);
  loadError = $state<string | null>(null);
  notFound = $state(false);
  /** Number of mutations in flight. */
  busy = $state(0);
  lastSubmit = $state<SubmitResult | null>(null);

  #seq = 0;
  #applied = 0;
  #poll: ReturnType<typeof setTimeout> | null = null;
  #destroyed = false;
  #lastTyped = 0;
  #loadedAt = 0;
  #onVisible = () => {
    if (!document.hidden) this.#schedulePoll(0);
  };
  #onInput = () => {
    this.#lastTyped = Date.now();
  };

  /** The "use your phone as the scanner" sheet; opened from several places. */
  linkOpen = $state(false);

  constructor(id: number) {
    this.id = id;
    document.addEventListener('visibilitychange', this.#onVisible);
    document.addEventListener('input', this.#onInput, true);
  }

  readonly lineById = $derived.by(() => {
    const map = new Map<number, ReceiptLineOut>();
    for (const r of this.trip?.receipts ?? []) for (const l of r.lines) map.set(l.id, l);
    return map;
  });

  readonly receiptById = $derived.by(() => {
    const map = new Map<number, ReceiptOut>();
    for (const r of this.trip?.receipts ?? []) map.set(r.id, r);
    return map;
  });

  readonly readOnly = $derived(this.trip?.status === 'submitted');

  /**
   * Grocy can't be reached and the server is working from its saved copy of
   * Grocy's data. Everything except sending to Grocy (and undoing) still works.
   */
  readonly grocyDown = $derived(this.trip?.grocy_reachable === false || meta.value?.grocy_reachable === false);

  readonly counts = $derived.by(() => {
    const items = this.trip?.items ?? [];
    return {
      scanned: items.filter((i) => i.source === 'scan').length,
      attention: items.filter((i) => i.state === 'needs_product').length,
      failed: items.filter((i) => i.state === 'failed').length,
      ready: items.filter((i) => i.state === 'ready').length,
      committed: items.filter((i) => i.state === 'committed').length,
      /** Items that the submit button will try to book: ready plus failed retries. */
      toAdd: items.filter((i) => i.state === 'ready' || (i.state === 'failed' && (i.product || i.new_product))).length,
    };
  });

  async load(opts: { quiet?: boolean } = {}): Promise<void> {
    const seq = ++this.#seq;
    try {
      const trip = await api.trip(this.id);
      this.loadError = null;
      this.#apply(trip, seq);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) this.notFound = true;
      else if (!this.trip) this.loadError = errorMessage(err);
      else if (!opts.quiet && !(err instanceof ApiError && err.offline)) reportError(err);
      if (!this.trip) this.#schedulePoll(); // keep trying until the first load lands
    }
  }

  #apply(trip: TripOut, seq: number): void {
    if (this.#destroyed || seq < this.#applied) return;
    this.#applied = seq;
    this.#loadedAt = Date.now();
    this.trip = trip;
    this.#schedulePoll();
  }

  /**
   * Runs a mutation that returns the full trip. Errors become a toast (and a
   * reload when the trip changed underneath us). Returns true on success.
   */
  async run(fn: () => Promise<TripOut>, opts: { success?: string; rethrow?: boolean } = {}): Promise<boolean> {
    const seq = ++this.#seq;
    this.busy++;
    try {
      const trip = await fn();
      this.#apply(trip, seq);
      if (opts.success) toasts.success(opts.success);
      return true;
    } catch (err) {
      this.#refreshIfGrocyDown(err);
      if (opts.rethrow) throw err;
      this.report(err);
      return false;
    } finally {
      this.busy--;
    }
  }

  report(err: unknown): void {
    reportError(err);
    if (err instanceof ApiError && (err.status === 409 || err.status === 404)) void this.load();
  }

  /**
   * An action needed Grocy and Grocy was down. Nothing changed, so the trip stays
   * as it is; ask the server again only so the "can't reach Grocy" notice shows.
   */
  #refreshIfGrocyDown(err: unknown): void {
    if (isGrocyUnreachable(err)) void this.load({ quiet: true });
  }

  /** Scans answer with just the one item; merge it in place. */
  mergeItem(item: ItemOut): void {
    if (!this.trip) return;
    const items = this.trip.items;
    const idx = items.findIndex((i) => i.id === item.id);
    const next = idx >= 0 ? items.map((i) => (i.id === item.id ? item : i)) : [...items, item];
    this.trip = { ...this.trip, items: next, item_count: next.length };
  }

  /** Bump the sequence so in-flight polls don't overwrite a newer local merge. */
  touch(): void {
    this.#applied = ++this.#seq;
  }

  async submit(): Promise<SubmitResult | null> {
    const seq = ++this.#seq;
    this.busy++;
    try {
      const result = await api.submit(this.id);
      this.#apply(result.trip, seq);
      this.lastSubmit = result;
      return result;
    } catch (err) {
      // Grocy being unreachable comes back as an error, not as a result: no
      // outcome is recorded, so nothing is shown as "couldn't be added".
      this.#refreshIfGrocyDown(err);
      this.report(err);
      return null;
    } finally {
      this.busy--;
    }
  }

  /**
   * The trip may be open on a second device (a phone doing the scanning while
   * this screen reviews), so keep asking the server for its change counter and
   * refetch only when it moved. Plain polling on purpose: it needs nothing from
   * the reverse proxy and recovers by itself after sleep or a network change.
   */
  #schedulePoll(ms?: number): void {
    this.#clearPoll();
    if (this.#destroyed || this.notFound) return;
    const delay = ms ?? (this.trip?.processing ? POLL_BUSY_MS : POLL_MS);
    this.#poll = setTimeout(() => {
      this.#poll = null;
      if (document.hidden) return; // resumed by visibilitychange
      void this.#check();
    }, delay);
  }

  async #check(): Promise<void> {
    const known = this.trip?.revision;
    try {
      if (known === undefined) return await this.load();
      const { revision } = await api.tripRevision(this.id);
      if (this.#destroyed) return;
      const changed = revision !== this.trip?.revision;
      // Grocy coming back doesn't count as a change to the trip, so look for that separately.
      const recheck = this.grocyDown && Date.now() - this.#loadedAt >= GROCY_RECHECK_MS;
      if (!changed && !recheck) return;
      // A change of our own is in flight (its answer brings the new state), or the
      // person is typing: look again on the next tick instead.
      if (this.busy > 0 || Date.now() - this.#lastTyped < TYPING_GRACE_MS) return;
      if (recheck) {
        this.#loadedAt = Date.now(); // even if this attempt fails, wait before the next one
        void meta.load();
      }
      await this.load({ quiet: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) this.notFound = true;
      // Offline or signed out elsewhere: stay quiet, the next real action reports it.
    } finally {
      this.#schedulePoll();
    }
  }

  #clearPoll(): void {
    if (this.#poll) clearTimeout(this.#poll);
    this.#poll = null;
  }

  destroy(): void {
    this.#destroyed = true;
    this.#clearPoll();
    document.removeEventListener('visibilitychange', this.#onVisible);
    document.removeEventListener('input', this.#onInput, true);
  }
}
