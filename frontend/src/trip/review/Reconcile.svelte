<script lang="ts">
  // Do the items' prices add up to what the receipts say? A hint, not a gate.
  import { money, plural } from '../../lib/format';
  import Icon from '../../components/Icon.svelte';
  import type { TripStore } from '../trip.svelte';

  let { store }: { store: TripStore } = $props();

  const r = $derived.by(() => {
    const trip = store.trip!;
    const ready = trip.receipts.filter((x) => x.status === 'ready');
    const counted = trip.items.filter((i) => i.state !== 'skipped');
    const itemsSum = counted.reduce((s, i) => s + (i.line_total ?? 0), 0);
    const priced = counted.filter((i) => i.line_total != null).length;
    let receiptSum: number | null = null;
    for (const x of ready) {
      const sub = x.subtotal ?? (x.total != null && x.tax != null ? x.total - x.tax : x.total);
      if (sub != null) receiptSum = (receiptSum ?? 0) + sub;
    }
    const unmatched = ready
      .flatMap((x) => x.lines)
      .filter((l) => l.matched_item_id == null && !l.dismissed);
    const unmatchedSum = unmatched.reduce((s, l) => s + (l.total_price ?? 0), 0);
    const dismissedSum = ready
      .flatMap((x) => x.lines)
      .filter((l) => l.matched_item_id == null && l.dismissed)
      .reduce((s, l) => s + (l.total_price ?? 0), 0);
    const diff = receiptSum == null ? null : receiptSum - itemsSum - dismissedSum;
    return { itemsSum, priced, total: counted.length, receiptSum, diff, unmatched: unmatched.length, unmatchedSum, dismissedSum };
  });

  const close = $derived(r.diff != null && Math.abs(r.diff) < 0.015);
</script>

<div class="reconcile">
  <dl>
    <div>
      <dt>Items</dt>
      <dd>{plural(r.total, 'item')}{#if r.priced < r.total}<span class="muted small">, {r.total - r.priced} without a price</span>{/if}</dd>
    </div>
    {#if r.priced > 0}
      <div>
        <dt>Their prices</dt>
        <dd class="big">{money(r.itemsSum)}</dd>
      </div>
    {/if}
    {#if r.receiptSum != null}
      <div>
        <dt>Receipt subtotal</dt>
        <dd class="big">{money(r.receiptSum)}</dd>
      </div>
    {/if}
  </dl>
  {#if r.diff != null}
    {#if close}
      <p class="verdict good"><Icon name="check" size={18} /> Prices match the receipt.</p>
    {:else if r.diff > 0 && r.unmatched > 0}
      <p class="verdict warn">
        <Icon name="info" size={18} />
        {money(r.diff)} isn't on an item yet. {plural(r.unmatched, 'receipt line')} below {r.unmatched === 1 ? 'has' : 'have'} no item ({money(r.unmatchedSum)}).
      </p>
    {:else}
      <p class="verdict warn">
        <Icon name="info" size={18} />
        {r.diff > 0 ? `${money(r.diff)} less than the receipt.` : `${money(-r.diff)} more than the receipt.`} Worth a quick look at prices and amounts.
      </p>
    {/if}
  {:else if store.trip?.receipts.length === 0}
    <p class="verdict small muted">Add the receipt to fill in prices and amounts.</p>
  {/if}
</div>

<style>
  .reconcile {
    padding: 14px 16px;
    border-radius: var(--r-lg);
    background: var(--surface);
    border: 2px solid var(--line);
  }
  dl {
    display: grid;
    grid-template-columns: repeat(3, auto);
    justify-content: space-between;
    gap: 12px;
    margin: 0;
  }
  dt {
    font-size: var(--fs-sm);
    color: var(--ink-2);
  }
  dd {
    margin: 0;
    font-weight: 700;
  }
  dd.big {
    font-size: var(--fs-lg);
    font-weight: 760;
  }
  @media (min-width: 960px) {
    dl {
      grid-template-columns: 1fr;
    }
    dl div {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
    }
  }
  .verdict {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid var(--line);
    font-size: var(--fs-sm);
    font-weight: 600;
  }
  .verdict :global(svg) {
    flex: none;
    margin-top: 1px;
  }
  .verdict.good {
    color: var(--basil);
  }
  .verdict.warn {
    color: var(--saffron-ink);
  }
</style>
