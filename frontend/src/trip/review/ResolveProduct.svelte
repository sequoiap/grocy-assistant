<script lang="ts">
  // For an unknown barcode: create a new product, or attach the barcode to one Grocy already has.
  import { api, ApiError, errorMessage, isGrocyUnreachable } from '../../lib/api';
  import type { IdName, ItemOut, NewProductDraft } from '../../lib/types';
  import Icon from '../../components/Icon.svelte';
  import ProductPicker from '../../components/ProductPicker.svelte';
  import NewProductForm from './NewProductForm.svelte';
  import type { TripStore } from '../trip.svelte';

  let { store, item }: { store: TripStore; item: ItemOut } = $props();

  let mode = $state<'choose' | 'create'>('choose');
  let pickerOpen = $state(false);
  let pickerQuery = $state('');
  let createName = $state('');
  let busy = $state(false);
  let error = $state<string | null>(null);
  let calm = $state(false);
  let imgFailed = $state(false);

  const lookup = $derived(item.lookup);
  const lineText = $derived(item.receipt_line_id ? store.lineById.get(item.receipt_line_id)?.description : null);
  const suggestedName = $derived(lookup?.suggested_name || lineText || '');

  async function link(p: IdName) {
    error = null;
    await store.run(() => api.patchItem(store.id, item.id, { product_id: p.id }), {
      success: item.barcode ? `Linked to ${p.name}; the barcode will be added to it` : `Linked to ${p.name}`,
    });
  }

  async function create(draft: NewProductDraft) {
    busy = true;
    error = null;
    try {
      await store.run(() => api.patchItem(store.id, item.id, { new_product: draft }), { rethrow: true });
      mode = 'choose';
    } catch (err) {
      error = errorMessage(err);
      calm = isGrocyUnreachable(err);
      // Grocy already has that name: offer to link to it instead.
      if (err instanceof ApiError && err.status === 409) pickerQuery = draft.name;
    } finally {
      busy = false;
    }
  }

  function openPicker(q = '') {
    pickerQuery = q || lookup?.name || suggestedName;
    pickerOpen = true;
  }
</script>

<div class="resolve">
  <div class="what">
    {#if lookup?.image_url && !imgFailed}
      <img src={lookup.image_url} alt="" referrerpolicy="no-referrer" onerror={() => (imgFailed = true)} />
    {/if}
    <div class="small">
      {#if lookup?.found}
        <p>Not in Grocy yet. The name was found online{#if lookup.source}&nbsp;<span class="muted">({lookup.source})</span>{/if}; change it if you like.</p>
      {:else if item.barcode}
        <p>Grocy doesn't know barcode <strong class="code">{item.barcode}</strong>, and it wasn't found online.</p>
      {:else}
        <p>Choose which Grocy product this is.</p>
      {/if}
    </div>
  </div>

  {#if mode === 'choose'}
    {#if item.suggestions.length}
      <div class="suggest">
        <p class="small muted">Already in Grocy? One tap links it:</p>
        <div class="chips">
          {#each item.suggestions as s (s.id)}
            <button type="button" class="chip suggest" onclick={() => link(s)}><Icon name="link" size={16} /> {s.name}</button>
          {/each}
        </div>
      </div>
    {/if}
    <div class="paths">
      <button
        type="button"
        class="btn attention"
        onclick={() => {
          createName = '';
          mode = 'create';
        }}
      >
        <Icon name="plus" /> New product
      </button>
      <button type="button" class="btn" onclick={() => openPicker()}>
        <Icon name="search" /> Find in Grocy
      </button>
    </div>
    {#if error}
      <p class="form-error">{error} <button class="linklike" onclick={() => openPicker(pickerQuery)}>Find it in Grocy</button></p>
    {/if}
  {:else}
    <NewProductForm
      initial={{ name: createName || suggestedName }}
      {busy}
      {error}
      {calm}
      submitLabel="Use this new product"
      onsubmit={create}
      oncancel={() => {
        mode = 'choose';
        error = null;
      }}
    />
  {/if}
</div>

<ProductPicker
  bind:open={pickerOpen}
  title="Which product is it?"
  initialQuery={pickerQuery}
  suggestions={item.suggestions}
  onpick={link}
  oncreate={(name) => {
    createName = name;
    mode = 'create';
  }}
/>

<style>
  .resolve {
    display: grid;
    gap: 12px;
  }
  .what {
    display: flex;
    gap: 12px;
    align-items: center;
  }
  .what img {
    flex: none;
    width: 52px;
    height: 52px;
    object-fit: contain;
    border-radius: 10px;
    background: #fff;
  }
  .code {
    letter-spacing: 0.03em;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 6px;
  }
  .paths {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
  }
  @media (max-width: 420px) {
    .paths {
      grid-template-columns: 1fr;
    }
  }
</style>
