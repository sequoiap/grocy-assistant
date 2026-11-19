<script lang="ts">
  // Everything about one item that can be changed before it goes to Grocy.
  import { api, errorMessage, isGrocyUnreachable } from '../../lib/api';
  import { money, qty } from '../../lib/format';
  import { meta } from '../../lib/session.svelte';
  import type { IdName, ItemOut, ItemPatch, NewProductDraft } from '../../lib/types';
  import Icon from '../../components/Icon.svelte';
  import ProductPicker from '../../components/ProductPicker.svelte';
  import StoreSelect from '../../components/StoreSelect.svelte';
  import LotsEditor from './LotsEditor.svelte';
  import NewProductForm from './NewProductForm.svelte';
  import type { TripStore } from '../trip.svelte';

  let { store, item }: { store: TripStore; item: ItemOut } = $props();

  const uid = $props.id();
  let pickerOpen = $state(false);
  let editDraft = $state(false);
  let draftError = $state<string | null>(null);
  let draftCalm = $state(false);
  let confirmRemove = $state(false);

  const inventory = $derived(store.trip?.kind === 'inventory');
  const receipts = $derived((store.trip?.receipts ?? []).filter((r) => r.status === 'ready' && r.lines.length));
  const itemNames = $derived(new Map((store.trip?.items ?? []).map((i) => [i.id, i.name])));

  function patch(body: ItemPatch, success?: string) {
    return store.run(() => api.patchItem(store.id, item.id, body), { success });
  }

  function numberFrom(e: Event): number | null {
    const raw = (e.currentTarget as HTMLInputElement).value.replace(',', '.');
    if (raw.trim() === '') return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : NaN;
  }

  async function saveDraft(draft: NewProductDraft) {
    draftError = null;
    try {
      await store.run(() => api.patchItem(store.id, item.id, { new_product: draft }), { rethrow: true });
      editDraft = false;
    } catch (err) {
      draftError = errorMessage(err);
      draftCalm = isGrocyUnreachable(err);
    }
  }

  function changeProduct(p: IdName) {
    void patch({ product_id: p.id }, `Now ${p.name}`);
  }
</script>

<div class="editor">
  <!-- product -->
  <section class="block">
    <h4>Product</h4>
    {#if item.new_product && !editDraft}
      <p>
        <strong>{item.new_product.name}</strong> will be created in Grocy, kept in
        {meta.locationName(item.new_product.location_id) ?? 'its location'}.
      </p>
      <div class="inline">
        <button type="button" class="btn small" onclick={() => (editDraft = true)}><Icon name="pencil" size={18} /> Edit new product</button>
        <button type="button" class="btn small" onclick={() => (pickerOpen = true)}><Icon name="link" size={18} /> Use an existing product</button>
      </div>
    {:else if item.new_product && editDraft}
      <NewProductForm initial={item.new_product} submitLabel="Save" error={draftError} calm={draftCalm} onsubmit={saveDraft} oncancel={() => (editDraft = false)} />
    {:else if item.product}
      <p>
        <strong>{item.product.name}</strong>
        {#if item.link_barcode && item.barcode}<span class="muted">; barcode {item.barcode} will be added to it</span>{/if}
      </p>
      <div class="inline">
        <button type="button" class="btn small" onclick={() => (pickerOpen = true)}><Icon name="link" size={18} /> Change product</button>
      </div>
    {/if}
  </section>

  <!-- receipt match -->
  {#if receipts.length}
    <section class="block">
      <label class="field" for="{uid}-line"><span>Line on the receipt</span></label>
      <select
        id="{uid}-line"
        value={item.receipt_line_id == null ? '' : String(item.receipt_line_id)}
        onchange={(e) => {
          const v = e.currentTarget.value;
          void patch({ receipt_line_id: v === '' ? null : Number(v) });
        }}
      >
        <option value="">Not on a receipt</option>
        {#each receipts as r (r.id)}
          <optgroup label={r.store_name ?? `Receipt ${r.id}`}>
            {#each r.lines.filter((l) => !l.dismissed || l.id === item.receipt_line_id) as l (l.id)}
              <option value={String(l.id)}>
                {l.description || l.raw_text}{l.total_price != null ? `, ${money(l.total_price)}` : ''}{l.matched_item_id && l.matched_item_id !== item.id
                  ? ` (now on ${itemNames.get(l.matched_item_id) ?? 'another item'})`
                  : ''}
              </option>
            {/each}
          </optgroup>
        {/each}
      </select>
      {#if item.receipt_line_id != null}
        {@const line = store.lineById.get(item.receipt_line_id)}
        {#if line}<p class="small muted printed">Printed as “{line.raw_text || line.description}”</p>{/if}
      {/if}
    </section>
  {/if}

  <!-- amount and price -->
  <section class="block two">
    <label class="field">
      <span>Amount ({item.pack_unit || 'packs'})</span>
      <input
        type="number"
        inputmode="decimal"
        min="0"
        step="any"
        value={item.quantity}
        onchange={(e) => {
          const n = numberFrom(e);
          if (n != null && n > 0) void patch({ quantity: n });
        }}
      />
      <small class="hint">
        {#if item.pack_factor !== 1}= {qty(item.stock_amount)} {item.stock_unit}.{/if}
        {item.quantity_source === 'manual' ? 'Set by you.' : item.quantity_source === 'receipt' ? 'From the receipt.' : item.quantity_source === 'scans' ? 'From scans.' : ''}
        {#if item.quantity_source === 'manual'}
          <button type="button" class="linklike" onclick={() => patch({ quantity: null })}>Use {item.receipt_line_id ? 'receipt' : 'default'}</button>
        {/if}
      </small>
    </label>
    <label class="field">
      <span>{inventory ? 'What it cost' : 'Price paid'} {#if inventory}<span class="opt">(optional)</span>{/if}</span>
      <input
        type="number"
        inputmode="decimal"
        min="0"
        step="0.01"
        value={item.line_total ?? ''}
        placeholder={inventory ? 'Leave empty if unknown' : 'Unknown'}
        onchange={(e) => {
          const n = numberFrom(e);
          if (n === null || (n >= 0 && !Number.isNaN(n))) void patch({ line_total: n });
        }}
      />
      <small class="hint">
        {#if item.unit_price != null && item.stock_amount !== 1}{money(item.unit_price)} per {item.stock_unit.toLowerCase()}.{/if}
        {item.price_source === 'manual' ? 'Set by you.' : item.price_source === 'receipt' ? 'From the receipt.' : ''}
        {#if item.price_source === 'manual'}
          <button type="button" class="linklike" onclick={() => patch({ line_total: null })}>Use receipt</button>
        {/if}
      </small>
    </label>
  </section>

  <section class="block">
    <LotsEditor {item} onlots={(lots) => patch({ lots })} ondue={(v) => patch({ due_date: v })} />
  </section>

  <section class="block two">
    <label class="field">
      <span>Kept in</span>
      <select
        value={item.location_id == null ? '' : String(item.location_id)}
        onchange={(e) => patch({ location_id: e.currentTarget.value ? Number(e.currentTarget.value) : null })}
      >
        <option value="">Product's default</option>
        {#each meta.value?.locations ?? [] as l (l.id)}<option value={String(l.id)}>{l.name}</option>{/each}
      </select>
    </label>
    <StoreSelect
      value={item.shopping_location_id}
      label={inventory ? 'Bought at (optional)' : 'Bought at'}
      emptyLabel={inventory ? "Don't know" : 'Not set'}
      onchange={(id) => patch({ shopping_location_id: id })}
    />
  </section>

  <section class="block">
    <label class="field">
      <span>Note for Grocy <span class="opt">(optional)</span></span>
      <input
        value={item.note ?? ''}
        maxlength="255"
        placeholder="e.g. on offer"
        onchange={(e) => patch({ note: e.currentTarget.value.trim() || null })}
      />
    </label>
  </section>

  <section class="block actions">
    {#if item.state === 'skipped'}
      <button type="button" class="btn" onclick={() => patch({ skipped: false })}><Icon name="undo" size={20} /> Add it after all</button>
    {:else}
      <button type="button" class="btn" onclick={() => patch({ skipped: true }, `${item.name} won't be added`)}>
        <Icon name="skip" size={20} /> Don't add to Grocy
      </button>
    {/if}
    {#if !confirmRemove}
      <button type="button" class="btn danger" onclick={() => (confirmRemove = true)}><Icon name="trash" size={20} /> Remove from {inventory ? 'inventory' : 'trip'}</button>
    {:else}
      <button type="button" class="btn danger" onclick={() => store.run(() => api.deleteItem(store.id, item.id), { success: `Removed ${item.name}` })}>
        <Icon name="trash" size={20} /> Yes, remove it
      </button>
    {/if}
  </section>
</div>

<ProductPicker
  bind:open={pickerOpen}
  title="Which product is it?"
  initialQuery={item.product?.name ?? item.new_product?.name ?? ''}
  onpick={changeProduct}
/>

<style>
  .editor {
    display: grid;
    gap: 18px;
    padding-top: 6px;
  }
  .block {
    display: grid;
    gap: 6px;
    min-width: 0;
  }
  h4 {
    font-size: var(--fs-sm);
    font-weight: 650;
    color: var(--ink-2);
    letter-spacing: 0;
  }
  .two {
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    align-items: start;
  }
  @media (max-width: 400px) {
    .two {
      grid-template-columns: 1fr;
    }
  }
  .inline {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 4px;
  }
  .printed {
    overflow-wrap: anywhere;
  }
  .opt {
    font-weight: 400;
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding-top: 4px;
    border-top: 1px solid var(--line);
    padding-top: 14px;
  }
</style>
