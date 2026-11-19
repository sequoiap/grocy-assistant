<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { api, errorMessage, isGrocyUnreachable } from '../../lib/api';
  import { plural, dateTime, qty, tripNoun } from '../../lib/format';
  import { navigate } from '../../lib/router.svelte';
  import { meta } from '../../lib/session.svelte';
  import { toasts, viewport } from '../../lib/ui.svelte';
  import type { ItemOut } from '../../lib/types';
  import Icon from '../../components/Icon.svelte';
  import Sheet from '../../components/Sheet.svelte';
  import ItemCard from './ItemCard.svelte';
  import ItemEditor from './ItemEditor.svelte';
  import ResolveProduct from './ResolveProduct.svelte';
  import BulkTable from './BulkTable.svelte';
  import LineRow from './LineRow.svelte';
  import Reconcile from './Reconcile.svelte';
  import SubmitOutcome from './SubmitOutcome.svelte';
  import type { TripStore } from '../trip.svelte';

  let { store }: { store: TripStore } = $props();

  let expanded = $state<number | null>(null);
  let bulkBusy = $state(false);
  let undoOpen = $state(false);
  let undoBusy = $state(false);
  let submitting = $state(false);

  const trip = $derived(store.trip!);
  const items = $derived(trip.items);
  const inventory = $derived(trip.kind === 'inventory');
  const noun = $derived(tripNoun(trip.kind));
  const thing = $derived(inventory ? 'product' : 'item');
  // Open, partly in Grocy already: some were added, others still wait for a product.
  const partly = $derived(!store.readOnly && store.counts.committed > 0 && !store.lastSubmit);
  const waiting = $derived(items.filter((i) => i.state !== 'committed' && i.state !== 'skipped').length);

  // Cards suit a phone; a big screen can show everything as an editable table.
  const VIEW_KEY = 'ga.reviewView';
  let chosenView = $state<'cards' | 'table' | null>(readView());
  const view = $derived(viewport.wide ? (chosenView ?? (inventory ? 'table' : 'cards')) : 'cards');

  function readView(): 'cards' | 'table' | null {
    try {
      const v = localStorage.getItem(VIEW_KEY);
      return v === 'cards' || v === 'table' ? v : null;
    } catch {
      return null;
    }
  }

  function setView(v: 'cards' | 'table') {
    chosenView = v;
    expanded = null;
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* not remembered */
    }
  }

  // The table's "all details" sheet. Looked up by id so it follows live changes.
  let detailId = $state<number | null>(null);
  const detailItem = $derived(detailId == null ? null : (items.find((i) => i.id === detailId) ?? null));
  let detailOpen = $state(false);
  function openDetails(item: ItemOut) {
    detailId = item.id;
    detailOpen = true;
  }

  /** Rows of one product stay together, wherever the first of them was. */
  function byProduct(list: ItemOut[]): ItemOut[] {
    const key = (i: ItemOut) =>
      i.product ? `p${i.product.id}` : i.new_product ? `n${i.new_product.name.toLowerCase()}` : `i${i.id}`;
    const first = new Map<string, number>();
    list.forEach((i, idx) => {
      if (!first.has(key(i))) first.set(key(i), idx);
    });
    return list
      .map((i, idx) => ({ i, idx }))
      .sort((a, b) => first.get(key(a.i))! - first.get(key(b.i))! || a.idx - b.idx)
      .map((x) => x.i);
  }

  const tableItems = $derived.by(() => {
    const order = (i: ItemOut) =>
      ({ needs_product: 0, failed: 1, ready: 2, skipped: 3, committed: 4 })[i.state] ?? 5;
    return byProduct([...items].sort((a, b) => order(a) - order(b)));
  });

  const pieces = $derived(items.filter((i) => i.state !== 'skipped').reduce((n, i) => n + i.stock_amount, 0));
  const dated = $derived(items.filter((i) => i.lots.length > 0 || i.due_source === 'manual').length);

  const groups = $derived.by(() => {
    const decide: ItemOut[] = [];
    const ready: ItemOut[] = [];
    const skipped: ItemOut[] = [];
    const done: ItemOut[] = [];
    for (const i of items) {
      if (i.state === 'needs_product' || i.state === 'failed') decide.push(i);
      else if (i.state === 'ready') ready.push(i);
      else if (i.state === 'skipped') skipped.push(i);
      else done.push(i);
    }
    // Items with something to check come first among the ready ones.
    ready.sort((a, b) => Number(b.warnings.length > 0) - Number(a.warnings.length > 0));
    decide.sort((a, b) => Number(a.state === 'failed') - Number(b.state === 'failed'));
    return { decide: byProduct(decide), ready: byProduct(ready), skipped, done: byProduct(done) };
  });

  const bulkCandidates = $derived(
    items.filter((i) => i.state === 'needs_product' && i.lookup?.suggested_name),
  );

  const lines = $derived.by(() => {
    const open: { line: (typeof trip.receipts)[number]['lines'][number]; store: string | null }[] = [];
    const dismissed: typeof open = [];
    for (const r of trip.receipts) {
      if (r.status !== 'ready') continue;
      for (const l of r.lines) {
        if (l.matched_item_id != null) continue;
        (l.dismissed ? dismissed : open).push({ line: l, store: trip.receipts.length > 1 ? r.store_name : null });
      }
    }
    return { open, dismissed };
  });

  const readOnly = $derived(store.readOnly);
  const toAdd = $derived(store.counts.toAdd);

  onMount(async () => {
    void meta.load();
    const m = /^#item-(\d+)$/.exec(location.hash);
    if (m) {
      expanded = Number(m[1]);
      await tick();
      document.getElementById(`item-${m[1]}`)?.scrollIntoView({ block: 'start' });
      history.replaceState(history.state, '', location.pathname);
    }
  });

  function toggle(id: number) {
    expanded = expanded === id ? null : id;
  }

  async function createAll() {
    const defaults = (await meta.load())?.new_product_defaults;
    if (!defaults || defaults.location_id == null || defaults.qu_id == null) {
      toasts.error("Grocy has no location or unit to use for new products yet. Add one in Grocy first.");
      return;
    }
    bulkBusy = true;
    const failures: string[] = [];
    let grocyDown: unknown = null;
    for (const i of bulkCandidates) {
      const name = i.lookup!.suggested_name;
      try {
        await store.run(
          () =>
            api.patchItem(store.id, i.id, {
              new_product: {
                name,
                location_id: defaults.location_id!,
                qu_id: defaults.qu_id!,
                product_group_id: defaults.product_group_id,
                default_best_before_days: defaults.default_best_before_days,
              },
            }),
          { rethrow: true },
        );
      } catch (err) {
        if (isGrocyUnreachable(err)) {
          grocyDown = err; // the rest would only get the same answer
          break;
        }
        failures.push(`${name}: ${errorMessage(err)}`);
      }
    }
    bulkBusy = false;
    if (grocyDown) store.report(grocyDown);
    else if (failures.length) toasts.error(`Some couldn't be set up. ${failures.join('. ')}`);
    else toasts.success('New products set up. They are created in Grocy when you press Add.');
  }

  async function submit() {
    submitting = true;
    expanded = null;
    const result = await store.submit();
    submitting = false;
    if (result) {
      await tick();
      document.getElementById('outcome')?.scrollIntoView({ block: 'start', behavior: 'smooth' });
    }
  }

  async function undo() {
    undoBusy = true;
    const ok = await store.run(() => api.undo(store.id), { success: 'Undone. The trip is open for changes again.' });
    undoBusy = false;
    // Close either way: if it didn't work, the reason is a toast that the sheet would cover.
    undoOpen = false;
    if (ok) store.lastSubmit = null;
  }

  const submitLabel = $derived(
    toAdd === 0
      ? 'Nothing ready to add'
      : store.counts.attention > 0
        ? `Add the ${plural(toAdd, `ready ${thing}`)} now`
        : inventory
          ? `Add ${plural(toAdd, 'product')} to Grocy's stock`
          : `Add ${plural(toAdd, 'item')} to Grocy`,
  );
</script>

<div class="review" class:readonly={readOnly} class:table-view={view === 'table'}>
  <div class="main">
    {#if viewport.wide && items.length > 0}
      <div class="view-switch" role="group" aria-label="Show the items as">
        <button type="button" class="btn small" class:ghost={view !== 'cards'} aria-pressed={view === 'cards'} onclick={() => setView('cards')}>
          <Icon name="review" size={18} /> List
        </button>
        <button type="button" class="btn small" class:ghost={view !== 'table'} aria-pressed={view === 'table'} onclick={() => setView('table')}>
          <Icon name="table" size={18} /> Table
        </button>
      </div>
    {/if}

    {#if store.lastSubmit}
      <SubmitOutcome {store} result={store.lastSubmit} onretry={submit} onundo={() => (undoOpen = true)} onclose={() => (store.lastSubmit = null)} />
    {:else if readOnly}
      <div class="done-banner" id="outcome">
        <Icon name="check" size={28} />
        <div>
          <p class="db-title">In Grocy since {trip.submitted_at ? dateTime(trip.submitted_at) : 'earlier'}</p>
          <p class="small">To change something, undo the {noun} first. That takes its {thing}s back out of Grocy's stock.</p>
        </div>
        <button type="button" class="btn" onclick={() => (undoOpen = true)}><Icon name="undo" size={20} /> Undo</button>
      </div>
    {/if}

    {#if partly}
      <div class="note partly">
        <Icon name="info" size={18} />
        <p>
          <strong>{plural(store.counts.committed, thing)} already in Grocy</strong> (listed as In Grocy).
          {#if waiting}{plural(waiting, 'other')} {waiting === 1 ? "isn't" : "aren't"} yet{#if store.counts.attention}: {store.counts.attention} still {store.counts.attention === 1 ? 'needs' : 'need'} a product first{/if}.{/if}
        </p>
      </div>
    {/if}

    {#if items.length === 0}
      <div class="empty">
        <h2>Nothing to review yet</h2>
        {#if inventory}
          <p class="muted">
            Scan what's in the cupboards, here or with your phone as the scanner. Everything you scan shows up here,
            ready for amounts and due dates.
          </p>
          <div class="empty-actions">
            <button type="button" class="btn primary" onclick={() => navigate(`/trips/${store.id}/scan`, { replace: true })}><Icon name="barcode" /> Start counting</button>
            {#if viewport.wide}
              <button type="button" class="btn" onclick={() => (store.linkOpen = true)}><Icon name="phone" /> Use phone as scanner</button>
            {/if}
          </div>
        {:else}
          <p class="muted">Scan what you bought, or add a receipt and pick products from its lines.</p>
          <div class="empty-actions">
            <button type="button" class="btn primary" onclick={() => navigate(`/trips/${store.id}/scan`, { replace: true })}><Icon name="barcode" /> Scan items</button>
            <button type="button" class="btn" onclick={() => navigate(`/trips/${store.id}/receipts`, { replace: true })}><Icon name="receipt" /> Add a receipt</button>
          </div>
        {/if}
      </div>
    {/if}

    {#if trip.processing}
      <div class="note"><span class="spinner"></span><p>A receipt is still being read. Amounts and prices fill in when it's done.</p></div>
    {/if}

    {#if view === 'table' && items.length > 0}
      {#if bulkCandidates.length > 1 && !readOnly}
        <div class="bulk">
          <p class="small">{bulkCandidates.length} new products have names from the barcode lookup.</p>
          <button type="button" class="btn small" onclick={createAll} disabled={bulkBusy}>
            {#if bulkBusy}<span class="spinner"></span>{/if} Create all with these names
          </button>
        </div>
      {/if}
      <BulkTable {store} items={tableItems} onopen={openDetails} />
    {/if}

    {#if view === 'cards' && groups.decide.length}
      <section class="group" aria-labelledby="g-decide">
        <header class="g-head">
          <h2 id="g-decide"><span class="dot attention"></span> {groups.decide.some((i) => i.state === 'needs_product') ? 'Needs a decision' : "Couldn't be added"}</h2>
          <span class="count">{groups.decide.length}</span>
        </header>
        {#if bulkCandidates.length > 1 && !readOnly}
          <div class="bulk">
            <p class="small">{bulkCandidates.length} new products have names from the barcode lookup.</p>
            <button type="button" class="btn small" onclick={createAll} disabled={bulkBusy}>
              {#if bulkBusy}<span class="spinner"></span>{/if} Create all with these names
            </button>
          </div>
        {/if}
        <ul class="items">
          {#each groups.decide as item (item.id)}
            <ItemCard {store} {item} expanded={expanded === item.id} ontoggle={() => toggle(item.id)} />
          {/each}
        </ul>
      </section>
    {/if}

    {#if view === 'cards' && groups.ready.length}
      <section class="group" aria-labelledby="g-ready">
        <header class="g-head">
          <h2 id="g-ready"><span class="dot ready"></span> Ready to add</h2>
          <span class="count">{groups.ready.length}</span>
        </header>
        <ul class="items">
          {#each groups.ready as item (item.id)}
            <ItemCard {store} {item} expanded={expanded === item.id} ontoggle={() => toggle(item.id)} />
          {/each}
        </ul>
      </section>
    {/if}

    {#if lines.open.length}
      <section class="group" aria-labelledby="g-lines">
        <header class="g-head">
          <h2 id="g-lines"><span class="dot lines"></span> On the receipt, not scanned</h2>
          <span class="count">{lines.open.length}</span>
        </header>
        <p class="g-hint small muted">Fruit, deli and other things without a barcode. Add the ones you keep track of in Grocy.</p>
        <ul class="lines">
          {#each lines.open as { line, store: storeName } (line.id)}
            <LineRow {store} {line} {storeName} />
          {/each}
        </ul>
      </section>
    {/if}

    {#if view === 'cards' && groups.skipped.length}
      <section class="group" aria-labelledby="g-skipped">
        <header class="g-head">
          <h2 id="g-skipped"><span class="dot"></span> Not adding</h2>
          <span class="count">{groups.skipped.length}</span>
        </header>
        <ul class="items">
          {#each groups.skipped as item (item.id)}
            <ItemCard {store} {item} expanded={expanded === item.id} ontoggle={() => toggle(item.id)} />
          {/each}
        </ul>
      </section>
    {/if}

    {#if lines.dismissed.length}
      <details class="dismissed">
        <summary>{plural(lines.dismissed.length, 'receipt line')} set aside as not groceries</summary>
        <ul class="lines">
          {#each lines.dismissed as { line, store: storeName } (line.id)}
            <LineRow {store} {line} {storeName} />
          {/each}
        </ul>
      </details>
    {/if}

    {#if view === 'cards' && groups.done.length}
      <section class="group" aria-labelledby="g-done">
        <header class="g-head">
          <h2 id="g-done"><span class="dot done"></span> In Grocy</h2>
          <span class="count">{groups.done.length}</span>
        </header>
        <ul class="items">
          {#each groups.done as item (item.id)}
            <ItemCard {store} {item} ontoggle={() => toggle(item.id)} />
          {/each}
        </ul>
      </section>
    {/if}
  </div>

  {#if items.length > 0}
    <aside class="aside" aria-label="Summary">
      {#if inventory}
        <div class="inv-summary">
          <p><strong>{plural(items.length, 'product')}</strong>, {qty(pieces)} in all</p>
          <p class="small muted">
            {#if dated}{plural(dated, 'product')} with due dates you set; the rest use their usual shelf life.{:else}Due dates are each product's usual shelf life until you set them.{/if}
            Added as an inventory correction, not a purchase.
          </p>
        </div>
      {:else}
        <Reconcile {store} />
      {/if}
      {#if !readOnly}
        <div class="submit-bar">
          {#if store.counts.attention > 0 && toAdd > 0}
            <p class="hint small">
              Adds the {qty(toAdd)} ready now. {plural(store.counts.attention, thing)} without a product {store.counts.attention === 1 ? "isn't" : "aren't"}
              included: {store.counts.attention === 1 ? 'it stays' : 'they stay'} here until you choose one, then add {store.counts.attention === 1 ? 'it' : 'them'} with this button.
            </p>
          {:else if store.counts.attention > 0}
            <p class="hint small">First choose a product for each {thing} Grocy doesn't know yet.</p>
          {:else if trip.processing}
            <p class="hint small">Waiting for the receipt to be read.</p>
          {/if}
          <button type="button" class="btn primary big block" disabled={toAdd === 0 || trip.processing || submitting || store.busy > 0} onclick={submit}>
            {#if submitting}<span class="spinner"></span> Adding to Grocy…{:else}{submitLabel}{/if}
          </button>
        </div>
        {#if store.counts.committed > 0 && !store.lastSubmit}
          <button type="button" class="btn ghost small undo-link" onclick={() => (undoOpen = true)}>
            <Icon name="undo" size={18} /> Undo the {plural(store.counts.committed, 'item')} already added
          </button>
        {/if}
      {/if}
    </aside>
  {/if}
</div>

<Sheet bind:open={detailOpen} title={detailItem?.name ?? 'Item'} wide onclose={() => (detailId = null)}>
  {#if detailItem}
    {#if detailItem.state === 'needs_product'}
      <ResolveProduct {store} item={detailItem} />
    {/if}
    <ItemEditor {store} item={detailItem} />
  {:else}
    <p class="muted">This item isn't on the list any more.</p>
  {/if}
</Sheet>

<Sheet bind:open={undoOpen} title="Undo this {noun}?">
  <p>
    This takes the {plural(store.counts.committed, thing)} this {noun} added back out of Grocy's stock and reopens the {noun} for changes.
    Products that were created stay in Grocy.
  </p>
  {#snippet footer()}
    <button type="button" class="btn" onclick={() => (undoOpen = false)}>Keep it</button>
    <button type="button" class="btn primary" onclick={undo} disabled={undoBusy}>
      {#if undoBusy}<span class="spinner"></span>{:else}<Icon name="undo" size={20} />{/if} Undo {noun}
    </button>
  {/snippet}
</Sheet>

<style>
  .review {
    display: grid;
  }
  .view-switch {
    display: flex;
    gap: 6px;
    justify-self: end;
    padding-top: 6px;
  }
  .view-switch .btn[aria-pressed='true'] {
    --btn-bg: var(--cobalt-soft);
    --btn-fg: var(--cobalt);
  }
  .note.partly {
    margin: 12px var(--gutter) 0;
  }
  .inv-summary {
    display: grid;
    gap: 6px;
    padding: 16px;
    border-radius: var(--r-lg);
    background: var(--surface);
    border: 2px solid var(--line);
  }
  .main {
    display: grid;
    gap: 8px;
    align-content: start;
    min-width: 0;
  }
  .main > .note {
    margin: 12px var(--gutter) 0;
  }
  .group {
    display: grid;
    padding-top: 14px;
  }
  .g-head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px var(--gutter);
  }
  .g-head h2 {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: var(--fs-lg);
  }
  .dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--line-strong);
    flex: none;
  }
  .dot.attention {
    background: var(--saffron);
  }
  .dot.ready {
    background: var(--cobalt);
  }
  .dot.lines {
    background: transparent;
    border: 3px solid var(--cobalt);
  }
  .dot.done {
    background: var(--basil);
  }
  .count {
    color: var(--ink-2);
    font-weight: 700;
  }
  .g-hint {
    padding: 0 var(--gutter) 8px;
    max-width: 60ch;
  }
  .bulk {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px 12px;
    margin: 0 var(--gutter) 10px;
    padding: 10px 12px 10px 14px;
    border-radius: var(--r-md);
    background: var(--saffron-soft);
    color: var(--saffron-ink);
    font-weight: 600;
  }
  .items,
  .lines {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
  }
  .lines {
    background: var(--surface);
  }
  .dismissed {
    margin: 10px var(--gutter) 0;
  }
  .dismissed summary {
    min-height: var(--tap);
    display: flex;
    align-items: center;
    color: var(--ink-2);
    font-weight: 650;
    cursor: pointer;
  }
  .dismissed .lines {
    background: transparent;
  }
  .empty {
    display: grid;
    gap: 10px;
    padding: 32px var(--gutter);
  }
  .empty-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 6px;
  }
  .done-banner {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px 14px;
    margin: 14px var(--gutter) 0;
    padding: 16px;
    border-radius: var(--r-lg);
    background: var(--basil-soft);
    color: var(--basil);
  }
  .done-banner > div {
    flex: 1;
    min-width: 200px;
  }
  .done-banner p.small {
    color: var(--ink-2);
  }
  .db-title {
    font-weight: 750;
    font-size: var(--fs-lg);
  }
  .aside {
    display: grid;
    gap: 12px;
    align-content: start;
  }
  .submit-bar {
    position: fixed;
    left: 0;
    right: 0;
    bottom: calc(var(--safe-b) + var(--nav-h));
    z-index: 25;
    padding: 10px var(--gutter) 10px;
    background: color-mix(in srgb, var(--paper) 92%, transparent);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border-top: 1px solid var(--line);
  }
  .hint {
    margin-bottom: 8px;
    color: var(--saffron-ink);
    font-weight: 650;
  }
  .undo-link {
    justify-self: center;
  }
  .readonly .aside {
    padding-bottom: 12px;
  }

  @media (max-width: 959px) {
    .aside {
      order: -1;
      padding: 12px var(--gutter) 0;
    }
    .undo-link {
      order: 2;
    }
  }

  @media (min-width: 960px) {
    .review {
      grid-template-columns: minmax(0, 1fr) 340px;
      gap: 32px;
      padding: 16px var(--gutter) 0;
      align-items: start;
    }
    .main {
      gap: 12px;
    }
    .main > .note,
    .bulk,
    .done-banner,
    .dismissed {
      margin-inline: 0;
    }
    .g-head,
    .g-hint {
      padding-inline: 4px;
    }
    .items {
      gap: 10px;
    }
    .lines {
      border: 2px solid var(--line);
      border-radius: var(--r-lg);
      overflow: hidden;
    }
    .aside {
      position: sticky;
      top: calc(var(--safe-t) + 136px);
      padding-top: 14px;
    }
    /* The table wants the full width; the summary and button sit above it. */
    .review.table-view {
      grid-template-columns: minmax(0, 1fr);
    }
    .table-view .aside {
      position: static;
      order: -1;
      grid-template-columns: minmax(0, 1fr) 340px;
      align-items: center;
      padding-top: 0;
    }
    .table-view .main {
      gap: 10px;
    }
    .submit-bar {
      position: static;
      padding: 0;
      background: none;
      backdrop-filter: none;
      border: 0;
    }
  }
</style>
