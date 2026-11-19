<script lang="ts">
  // Every item as one row of inputs, for a big screen while a phone does the scanning.
  // Changes save as soon as a field is left; ticked rows can be changed all at once.
  import { api } from '../../lib/api';
  import { addDaysISO, money, qty } from '../../lib/format';
  import { meta } from '../../lib/session.svelte';
  import type { BulkItemPatch, ItemOut, ItemPatch, Lot } from '../../lib/types';
  import Icon from '../../components/Icon.svelte';
  import type { TripStore } from '../trip.svelte';

  let {
    store,
    items,
    onopen,
  }: {
    store: TripStore;
    /** In display order; rows of the same product are next to each other. */
    items: ItemOut[];
    /** Open the full details of one item (product choice, note, everything else). */
    onopen: (item: ItemOut) => void;
  } = $props();

  let selected = $state<Set<number>>(new Set());
  let bulkDue = $state('');

  const inventory = $derived(store.trip?.kind === 'inventory');
  const editable = $derived(items.filter((i) => i.state !== 'committed'));
  // Forget ticks on rows that went away (removed on another device, or booked).
  const ticked = $derived(editable.filter((i) => selected.has(i.id)));
  const allTicked = $derived(editable.length > 0 && ticked.length === editable.length);
  const locations = $derived(meta.value?.locations ?? []);
  const stores = $derived(meta.value?.stores ?? []);

  function key(i: ItemOut): string {
    if (i.product) return `p${i.product.id}`;
    if (i.new_product) return `n${i.new_product.name.toLowerCase()}`;
    return `i${i.id}`;
  }

  function toggle(id: number) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selected = next;
  }

  function toggleAll() {
    selected = allTicked ? new Set() : new Set(editable.map((i) => i.id));
  }

  function patch(item: ItemOut, body: ItemPatch) {
    return store.run(() => api.patchItem(store.id, item.id, body));
  }

  async function bulk(body: Omit<BulkItemPatch, 'item_ids'>, success: string) {
    const ids = ticked.map((i) => i.id);
    if (!ids.length) return;
    await store.run(() => api.patchItems(store.id, { item_ids: ids, ...body }), { success });
  }

  function num(e: Event): number | null {
    const raw = (e.currentTarget as HTMLInputElement).value.replace(',', '.').trim();
    if (raw === '') return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : NaN;
  }

  function setLots(item: ItemOut, lots: Lot[]) {
    return patch(item, { lots });
  }

  function addLot(item: ItemOut) {
    const due = item.due_date === 'never' ? addDaysISO(30) : item.due_date;
    return setLots(item, [...item.lots, { amount: 1, due_date: due }]);
  }

  function unitOf(item: ItemOut): string {
    return item.pack_factor !== 1 && item.pack_unit ? item.pack_unit : item.stock_unit;
  }
</script>

<div class="bulk-table">
  {#if ticked.length}
    <div class="bar" role="toolbar" aria-label="Change the ticked items">
      <strong>{ticked.length} ticked</strong>
      <span class="ctl">
        <label class="sr-only" for="bulk-due">Due date for the ticked items</label>
        <input id="bulk-due" type="date" bind:value={bulkDue} />
        <button type="button" class="btn small" disabled={!bulkDue} onclick={() => bulk({ due_date: bulkDue }, 'Due date set')}>Set date</button>
        <button type="button" class="btn small ghost" onclick={() => bulk({ due_date: 'never' }, "Set to doesn't expire")}>Doesn't expire</button>
        <button type="button" class="btn small ghost" onclick={() => bulk({ due_date: null }, 'Back to their usual shelf life')}>Usual shelf life</button>
      </span>
      <span class="ctl">
        <label class="sr-only" for="bulk-loc">Kept in, for the ticked items</label>
        <select
          id="bulk-loc"
          value=""
          onchange={(e) => {
            const v = e.currentTarget.value;
            e.currentTarget.value = '';
            if (v) void bulk({ location_id: v === 'default' ? null : Number(v) }, 'Location set');
          }}
        >
          <option value="">Kept in…</option>
          <option value="default">Each product's default</option>
          {#each locations as l (l.id)}<option value={String(l.id)}>{l.name}</option>{/each}
        </select>
      </span>
      <span class="ctl">
        <label class="sr-only" for="bulk-store">Store, for the ticked items</label>
        <select
          id="bulk-store"
          value=""
          onchange={(e) => {
            const v = e.currentTarget.value;
            e.currentTarget.value = '';
            if (v) void bulk({ shopping_location_id: v === 'none' ? null : Number(v) }, 'Store set');
          }}
        >
          <option value="">Bought at…</option>
          <option value="none">Don't know</option>
          {#each stores as s (s.id)}<option value={String(s.id)}>{s.name}</option>{/each}
        </select>
      </span>
      <span class="ctl end">
        <button type="button" class="btn small ghost" onclick={() => bulk({ skipped: true }, "They won't be added")}>
          <Icon name="skip" size={18} /> Don't add
        </button>
        <button type="button" class="btn small ghost" onclick={() => bulk({ skipped: false }, 'They will be added')}>
          <Icon name="undo" size={18} /> Add after all
        </button>
        <button type="button" class="btn small ghost icon" aria-label="Untick all" onclick={() => (selected = new Set())}>
          <Icon name="x" size={18} />
        </button>
      </span>
    </div>
  {/if}

  <div class="scroll">
    <table>
      <thead>
        <tr>
          <th class="tick">
            <input type="checkbox" aria-label="Tick all" checked={allTicked} indeterminate={ticked.length > 0 && !allTicked} onchange={toggleAll} disabled={!editable.length} />
          </th>
          <th>Product</th>
          <th class="num">Amount</th>
          <th>Due date</th>
          <th>Kept in</th>
          <th>Bought at</th>
          <th class="num">{inventory ? 'Cost' : 'Price'}</th>
        </tr>
      </thead>
      <tbody>
        {#each items as item, idx (item.id)}
          {@const locked = store.readOnly || item.state === 'committed'}
          {@const needs = item.state === 'needs_product'}
          {@const same = idx > 0 && key(items[idx - 1]) === key(item)}
          <tr class="row {item.state}" class:same class:ticked={selected.has(item.id)} id="item-{item.id}">
            <td class="tick">
              {#if !locked}
                <input type="checkbox" aria-label="Tick {item.name}" checked={selected.has(item.id)} onchange={() => toggle(item.id)} />
              {/if}
            </td>
            <td class="product">
              {#if needs}
                <button type="button" class="pick" onclick={() => onopen(item)}>
                  <span class="name">{item.lookup?.suggested_name || item.name}</span>
                  <span class="tag attention">Choose a product</span>
                </button>
              {:else}
                <span class="name">
                  {#if locked}{item.name}{:else}<button type="button" class="open" title="All details" onclick={() => onopen(item)}>{item.name}</button>{/if}
                  {#if item.new_product}<span class="tag new">New</span>{/if}
                  {#if item.state === 'skipped'}<span class="tag">Not adding</span>{/if}
                  {#if item.state === 'committed'}<span class="tag done">In Grocy</span>{/if}
                </span>
              {/if}
              <span class="sub small muted">
                {#if item.barcode}<span>{item.barcode}</span>{/if}
                {#if item.in_stock && !locked}<span class="stock">Grocy has {qty(item.in_stock)}</span>{/if}
              </span>
              {#if item.state === 'failed' && item.error}<span class="err small">Grocy said: {item.error}</span>{/if}
              {#if item.warnings.length && !locked}
                <span class="warn small" title={item.warnings.join('\n')}><Icon name="alert" size={14} /> {item.warnings[0]}</span>
              {/if}
            </td>
            <td class="num amount">
              {#if locked}
                {qty(item.committed_amount ?? item.stock_amount)} {item.stock_unit}
              {:else}
                <input
                  type="number"
                  inputmode="decimal"
                  min="0"
                  step="any"
                  aria-label="Amount of {item.name}"
                  value={item.quantity}
                  onchange={(e) => {
                    const n = num(e);
                    if (n != null && n > 0) void patch(item, { quantity: n });
                    else e.currentTarget.value = String(item.quantity);
                  }}
                />
                <span class="unit small muted">
                  {unitOf(item)}{#if item.pack_factor !== 1}<br />= {qty(item.stock_amount)} {item.stock_unit}{/if}
                </span>
              {/if}
            </td>
            <td class="due">
              {#if locked}
                {item.due_date === 'never' ? "Doesn't expire" : item.due_date}
              {:else}
                {#if item.rest_amount > 0 || !item.lots.length}
                  <div class="due-row">
                    {#if item.lots.length}<span class="small muted lot-n">{qty(item.rest_amount)} ×</span>{/if}
                    <input
                      type="date"
                      class:default={item.due_source === 'default'}
                      aria-label="Due date for {item.name}"
                      value={item.due_date === 'never' ? '' : item.due_date}
                      onchange={(e) => {
                        const v = e.currentTarget.value;
                        void patch(item, { due_date: v || null });
                      }}
                    />
                  </div>
                  <span class="small muted due-note">
                    {#if item.due_date === 'never'}Doesn't expire{:else if item.due_source === 'default'}Usual shelf life{/if}
                    {#if item.due_source === 'manual'}
                      <button type="button" class="linklike" onclick={() => patch(item, { due_date: null })}>Usual</button>
                    {:else if item.due_date !== 'never'}
                      <button type="button" class="linklike" onclick={() => patch(item, { due_date: 'never' })}>Never</button>
                    {/if}
                  </span>
                {/if}
                {#each item.lots as lot, i (i)}
                  <div class="due-row lot">
                    <input
                      class="lot-amount"
                      type="number"
                      inputmode="decimal"
                      min="0"
                      step="any"
                      aria-label="How many of {item.name} are due on this date"
                      value={lot.amount}
                      onchange={(e) => {
                        const n = num(e);
                        if (n != null && n > 0) void setLots(item, item.lots.map((l, j) => (j === i ? { ...l, amount: n } : l)));
                        else e.currentTarget.value = String(lot.amount);
                      }}
                    />
                    <span class="small muted">×</span>
                    <input
                      type="date"
                      aria-label="Due date"
                      value={lot.due_date === 'never' ? '' : lot.due_date}
                      onchange={(e) => {
                        const v = e.currentTarget.value;
                        if (v) void setLots(item, item.lots.map((l, j) => (j === i ? { ...l, due_date: v } : l)));
                      }}
                    />
                    <button type="button" class="btn ghost icon small" aria-label="Remove this date" onclick={() => setLots(item, item.lots.filter((_, j) => j !== i))}>
                      <Icon name="x" size={16} />
                    </button>
                  </div>
                {/each}
                <button type="button" class="linklike small add-lot" onclick={() => addLot(item)}>+ another date</button>
              {/if}
            </td>
            <td>
              {#if locked}
                {locations.find((l) => l.id === item.location_id)?.name ?? ''}
              {:else}
                <select
                  aria-label="Kept in, for {item.name}"
                  value={item.location_id == null ? '' : String(item.location_id)}
                  onchange={(e) => patch(item, { location_id: e.currentTarget.value ? Number(e.currentTarget.value) : null })}
                >
                  {#if item.location_id == null}<option value="">Product's default</option>{/if}
                  {#each locations as l (l.id)}<option value={String(l.id)}>{l.name}</option>{/each}
                </select>
              {/if}
            </td>
            <td>
              {#if locked}
                {stores.find((s) => s.id === item.shopping_location_id)?.name ?? ''}
              {:else}
                <select
                  aria-label="Bought at, for {item.name}"
                  value={item.shopping_location_id == null ? '' : String(item.shopping_location_id)}
                  onchange={(e) => patch(item, { shopping_location_id: e.currentTarget.value ? Number(e.currentTarget.value) : null })}
                >
                  <option value="">{inventory ? "Don't know" : 'Not set'}</option>
                  {#each stores as s (s.id)}<option value={String(s.id)}>{s.name}</option>{/each}
                </select>
              {/if}
            </td>
            <td class="num price">
              {#if locked}
                {money(item.line_total)}
              {:else}
                <input
                  type="number"
                  inputmode="decimal"
                  min="0"
                  step="0.01"
                  aria-label="{inventory ? 'What it cost' : 'Price paid'}, {item.name}"
                  placeholder="—"
                  value={item.line_total ?? ''}
                  onchange={(e) => {
                    const n = num(e);
                    if (n === null || (n >= 0 && !Number.isNaN(n))) void patch(item, { line_total: n });
                  }}
                />
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</div>

<style>
  .bulk-table {
    display: grid;
    gap: 10px;
    min-width: 0;
  }
  .bar {
    position: sticky;
    top: calc(var(--safe-t) + 120px);
    z-index: 5;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 14px;
    padding: 10px 14px;
    border-radius: var(--r-md);
    background: var(--cobalt-soft);
    box-shadow: var(--shadow);
  }
  .ctl {
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .ctl.end {
    margin-left: auto;
  }
  .bar input,
  .bar select {
    width: auto;
    min-height: 40px;
    padding-block: 6px;
  }
  .scroll {
    overflow-x: auto;
    border: 2px solid var(--line);
    border-radius: var(--r-lg);
    background: var(--surface);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--fs-sm);
  }
  th {
    position: sticky;
    top: 0;
    text-align: left;
    padding: 10px 8px;
    font-weight: 700;
    color: var(--ink-2);
    background: var(--surface-2);
    white-space: nowrap;
  }
  td {
    padding: 8px;
    vertical-align: top;
    border-top: 1px solid var(--line);
  }
  /* Rows of one product read as one block. */
  tr.same td {
    border-top-color: transparent;
  }
  tr.same td.product .name {
    color: var(--ink-2);
  }
  tr.ticked td {
    background: color-mix(in srgb, var(--cobalt-soft) 55%, transparent);
  }
  tr.needs_product td:first-child {
    box-shadow: inset 5px 0 0 var(--saffron);
  }
  tr.failed td:first-child {
    box-shadow: inset 5px 0 0 var(--tomato);
  }
  tr.skipped td {
    opacity: 0.6;
  }
  tr.skipped .name {
    text-decoration: line-through;
  }
  tr.committed td {
    color: var(--ink-2);
  }
  .tick {
    width: 36px;
    text-align: center;
  }
  .tick input {
    width: 20px;
    height: 20px;
    margin-top: 12px;
  }
  th.tick input {
    margin-top: 0;
  }
  .product {
    min-width: 160px;
  }
  .name {
    display: block;
    font-weight: 700;
    font-size: var(--fs-body);
    line-height: 1.25;
  }
  .sub {
    display: flex;
    flex-wrap: wrap;
    gap: 2px 10px;
    margin-top: 2px;
  }
  .stock {
    color: var(--saffron-ink);
    font-weight: 650;
  }
  .warn,
  .err {
    display: flex;
    gap: 4px;
    align-items: flex-start;
    margin-top: 4px;
    font-weight: 600;
    color: var(--saffron-ink);
    max-width: 34ch;
  }
  .err {
    color: var(--tomato);
  }
  .pick {
    display: grid;
    gap: 4px;
    padding: 0;
    border: 0;
    background: none;
    text-align: left;
    font: inherit;
    color: inherit;
    cursor: pointer;
  }
  .tag {
    display: inline-block;
    vertical-align: 0.1em;
    margin-left: 6px;
    padding: 1px 8px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 750;
    background: var(--surface-2);
    color: var(--ink-2);
  }
  .pick .tag {
    margin-left: 0;
    justify-self: start;
  }
  .tag.new {
    background: var(--cobalt-soft);
    color: var(--cobalt);
  }
  .tag.attention {
    background: var(--saffron);
    color: var(--on-saffron);
  }
  .tag.done {
    background: var(--basil-soft);
    color: var(--basil);
  }
  td input,
  td select {
    min-height: 40px;
    padding: 6px 8px;
    border-radius: var(--r-sm);
  }
  td select {
    padding-right: 32px;
    background-position: right 8px center;
    min-width: 110px;
  }
  .num {
    text-align: right;
  }
  /* Spin buttons only crowd out the number in a narrow cell. */
  td input[type='number'] {
    appearance: textfield;
    -moz-appearance: textfield;
  }
  td input[type='number']::-webkit-inner-spin-button,
  td input[type='number']::-webkit-outer-spin-button {
    -webkit-appearance: none;
    margin: 0;
  }
  /* (Prefixed so these beat the app-wide "inputs are full width" rule.) */
  .bulk-table td.amount input {
    width: 4.5rem;
    min-width: 4.5rem;
    text-align: right;
  }
  .unit {
    display: block;
    margin-top: 2px;
  }
  .bulk-table td.price input {
    width: 5.5rem;
    min-width: 5.5rem;
    text-align: right;
  }
  .due {
    min-width: 0;
  }
  .due-row {
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .due-row.lot {
    margin-top: 6px;
  }
  .bulk-table .due-row input[type='date'] {
    flex: none;
    width: 160px;
  }
  input.default {
    color: var(--ink-2);
    border-style: dashed;
  }
  .bulk-table td input.lot-amount {
    width: 3.5rem;
    min-width: 3.5rem;
    flex: none;
    text-align: right;
  }
  .lot-n {
    white-space: nowrap;
  }
  .due-note {
    display: flex;
    gap: 8px;
    margin-top: 2px;
  }
  .add-lot {
    display: block;
    margin-top: 4px;
  }
  .open {
    padding: 0;
    border: 0;
    background: none;
    font: inherit;
    color: inherit;
    text-align: left;
    cursor: pointer;
    text-decoration: underline dotted var(--line-strong);
    text-underline-offset: 0.2em;
  }
  .open:hover {
    color: var(--cobalt);
  }
</style>
