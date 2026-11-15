<script lang="ts">
  // A receipt line no scan was matched to: produce, deli, bags, deposits...
  import { api, errorMessage, isGrocyUnreachable } from '../../lib/api';
  import { money, qty } from '../../lib/format';
  import type { IdName, NewProductDraft, ReceiptLineOut } from '../../lib/types';
  import Icon from '../../components/Icon.svelte';
  import ProductPicker from '../../components/ProductPicker.svelte';
  import Sheet from '../../components/Sheet.svelte';
  import NewProductForm from './NewProductForm.svelte';
  import type { TripStore } from '../trip.svelte';

  let { store, line, storeName }: { store: TripStore; line: ReceiptLineOut; storeName: string | null } = $props();

  let pickerOpen = $state(false);
  let createOpen = $state(false);
  let createName = $state('');
  let createError = $state<string | null>(null);
  let createCalm = $state(false);
  let createBusy = $state(false);
  let matchOpen = $state(false);

  // Scanned items that aren't on any receipt line yet.
  const loose = $derived(
    (store.trip?.items ?? []).filter(
      (i) => i.receipt_line_id == null && i.state !== 'committed' && i.state !== 'skipped',
    ),
  );

  function friendly(text: string): string {
    return text === text.toUpperCase() ? text.toLowerCase().replace(/\b\p{L}/gu, (c) => c.toUpperCase()) : text;
  }

  function toItem(p: IdName) {
    return store.run(() => api.lineToItem(line.id, { product_id: p.id }), { success: `Added ${p.name}` });
  }

  async function create(draft: NewProductDraft) {
    createBusy = true;
    createError = null;
    try {
      await store.run(() => api.lineToItem(line.id, { new_product: draft }), { rethrow: true });
      createOpen = false;
    } catch (err) {
      createError = errorMessage(err);
      createCalm = isGrocyUnreachable(err);
    } finally {
      createBusy = false;
    }
  }

  async function matchTo(itemId: number) {
    matchOpen = false;
    await store.run(() => api.patchItem(store.id, itemId, { receipt_line_id: line.id }));
  }

  function dismiss(on: boolean) {
    return store.run(() => api.patchLine(line.id, { dismissed: on }));
  }

  const detail = $derived.by(() => {
    const parts: string[] = [];
    if (line.weight) parts.push(`${qty(line.weight)} ${line.weight_unit ?? ''}`.trim());
    else if (line.quantity !== 1) parts.push(`${qty(line.quantity)}×`);
    if (line.discount) parts.push(`${money(line.discount)} off`);
    if (storeName) parts.push(storeName);
    return parts.join(', ');
  });
</script>

<li class="line" class:dismissed={line.dismissed}>
  <div class="top">
    <div class="text">
      <p class="desc">{line.description || line.raw_text}</p>
      <p class="small muted">
        {#if line.raw_text && line.raw_text !== line.description}<span class="raw">“{line.raw_text}”</span>{/if}
        {detail}
      </p>
    </div>
    <span class="amount">{money(line.total_price)}</span>
  </div>

  {#if line.dismissed}
    <button type="button" class="btn small" onclick={() => dismiss(false)}><Icon name="undo" size={18} /> Restore</button>
  {:else if !store.readOnly}
    <div class="actions">
      {#if line.suggested_product}
        <button type="button" class="btn small primary" onclick={() => toItem(line.suggested_product!)}>
          <Icon name="check" size={18} /> {line.suggested_product.name}
        </button>
      {/if}
      <button type="button" class="btn small" onclick={() => (pickerOpen = true)}>
        <Icon name="box" size={18} /> {line.suggested_product ? 'Something else' : 'Choose product'}
      </button>
      {#if loose.length}
        <button type="button" class="btn small" onclick={() => (matchOpen = true)}>
          <Icon name="link" size={18} /> It's a scanned item
        </button>
      {/if}
      <button type="button" class="btn small ghost" onclick={() => dismiss(true)}>Not groceries</button>
    </div>
  {/if}
</li>

<ProductPicker
  bind:open={pickerOpen}
  title="What is “{line.description || line.raw_text}”?"
  initialQuery={friendly(line.description)}
  suggestions={line.suggested_product ? [line.suggested_product] : []}
  onpick={toItem}
  oncreate={(name) => {
    createName = name || friendly(line.description);
    createError = null;
    createOpen = true;
  }}
/>

<Sheet bind:open={createOpen} title="New product">
  {#if createOpen}
    <NewProductForm initial={{ name: createName }} busy={createBusy} error={createError} calm={createCalm} submitLabel="Add to this trip" onsubmit={create} />
  {/if}
</Sheet>

<Sheet bind:open={matchOpen} title="Which scanned item is this?">
  <p class="small muted">Items you scanned that aren't on a receipt yet.</p>
  <ul class="pick">
    {#each loose as i (i.id)}
      <li>
        <button type="button" onclick={() => matchTo(i.id)}>
          <span>{i.state === 'needs_product' ? i.lookup?.suggested_name || i.barcode || i.name : i.name}</span>
          {#if i.barcode}<span class="small muted">{i.barcode}</span>{/if}
        </button>
      </li>
    {/each}
  </ul>
</Sheet>

<style>
  .line {
    display: grid;
    gap: 10px;
    padding: 14px var(--gutter);
    border-bottom: 1px solid var(--line);
  }
  .line.dismissed {
    padding-block: 10px;
  }
  .line.dismissed .desc {
    color: var(--ink-2);
  }
  .top {
    display: flex;
    gap: 12px;
    align-items: flex-start;
  }
  .text {
    flex: 1;
    min-width: 0;
  }
  .desc {
    font-weight: 700;
  }
  .raw {
    margin-right: 6px;
  }
  .amount {
    font-weight: 750;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .pick {
    list-style: none;
    margin: 10px 0 0;
    padding: 0;
  }
  .pick button {
    width: 100%;
    display: grid;
    gap: 2px;
    min-height: 56px;
    padding: 10px 6px;
    border: 0;
    border-bottom: 1px solid var(--line);
    background: none;
    color: var(--ink);
    font: inherit;
    font-weight: 650;
    text-align: left;
    cursor: pointer;
  }
  .pick button:hover {
    background: var(--cobalt-soft);
  }
</style>
