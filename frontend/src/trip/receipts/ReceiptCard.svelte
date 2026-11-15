<script lang="ts">
  import { api } from '../../lib/api';
  import { money, shortDate, plural } from '../../lib/format';
  import type { ReceiptOut } from '../../lib/types';
  import Icon from '../../components/Icon.svelte';
  import Sheet from '../../components/Sheet.svelte';
  import StoreSelect from '../../components/StoreSelect.svelte';
  import type { TripStore } from '../trip.svelte';

  let { store, receipt, index }: { store: TripStore; receipt: ReceiptOut; index: number } = $props();

  let photosOpen = $state(false);
  let confirmDelete = $state(false);
  let editingName = $state(false);
  let nameDraft = $state('');

  const ro = $derived(store.readOnly);
  const title = $derived(receipt.store_name || `Receipt ${index + 1}`);
  const activeLines = $derived(receipt.lines.filter((l) => !l.dismissed));
  const matched = $derived(activeLines.filter((l) => l.matched_item_id != null).length);

  function patch(body: Parameters<typeof api.patchReceipt>[1]) {
    return store.run(() => api.patchReceipt(receipt.id, body));
  }

  function reread(useAI: boolean) {
    return store.run(() => api.reprocessReceipt(receipt.id, useAI));
  }

  async function remove() {
    const ok = await store.run(() => api.deleteReceipt(receipt.id), { success: 'Receipt deleted' });
    if (ok) confirmDelete = false;
  }

  async function saveName(e: SubmitEvent) {
    e.preventDefault();
    const ok = await patch({ store_name: nameDraft.trim() || null });
    if (ok) editingName = false;
  }
</script>

<article class="receipt {receipt.status}" aria-labelledby="r-{receipt.id}">
  <header>
    <button type="button" class="thumb" onclick={() => (photosOpen = true)} aria-label="View photo of {title}">
      {#if receipt.images[0]}
        <img src={receipt.images[0].url} alt="" loading="lazy" />
      {/if}
      {#if receipt.images.length > 1}<span class="pages">{receipt.images.length}</span>{/if}
    </button>
    <div class="head-text">
      {#if editingName}
        <form class="name-form" onsubmit={saveName}>
          <input bind:value={nameDraft} aria-label="Store name on receipt" maxlength="120" />
          <button class="btn small primary">Save</button>
        </form>
      {:else}
        <h3 id="r-{receipt.id}">
          {receipt.status === 'processing' && !receipt.store_name ? 'Reading receipt…' : title}
        </h3>
      {/if}
      <p class="small muted">
        {#if receipt.status === 'processing'}
          This usually takes a few seconds.
        {:else if receipt.status === 'failed'}
          Couldn't read this receipt
        {:else}
          {receipt.purchased_on ? shortDate(receipt.purchased_on) : 'No date found'}{#if receipt.total != null}, total {money(receipt.total)}{/if}
        {/if}
      </p>
    </div>
    {#if receipt.status === 'processing'}
      <span class="spinner" aria-hidden="true"></span>
    {/if}
  </header>

  {#if receipt.status === 'processing'}
    <div class="reading" aria-hidden="true"><span></span></div>
  {:else if receipt.status === 'failed'}
    <div class="note bad"><Icon name="alert" size={18} /><p>{receipt.error || 'The text on this photo could not be read.'}</p></div>
    {#if !ro}
      <div class="actions">
        <button type="button" class="btn" onclick={() => reread(false)}><Icon name="refresh" size={20} /> Try again</button>
        {#if store.trip?.ai_available}
          <button type="button" class="btn" onclick={() => reread(true)}><Icon name="spark" size={20} /> Try with AI</button>
        {/if}
        <button type="button" class="btn danger" onclick={() => (confirmDelete = true)}><Icon name="trash" size={20} /> Delete</button>
      </div>
    {/if}
  {:else}
    <dl class="facts">
      <div>
        <dt>Lines</dt>
        <dd>{plural(activeLines.length, 'line')}, {matched} matched to scans</dd>
      </div>
      {#if receipt.subtotal != null || receipt.tax != null}
        <div>
          <dt>Subtotal</dt>
          <dd>{money(receipt.subtotal)}{#if receipt.tax != null}<span class="muted">, tax {money(receipt.tax)}</span>{/if}</dd>
        </div>
      {/if}
      <div>
        <dt>Read by</dt>
        <dd>
          {receipt.method === 'ai' ? 'AI' : 'Built-in text recognition'}{#if receipt.confidence != null}<span class="muted">, {Math.round(receipt.confidence * 100)}% sure</span>{/if}
        </dd>
      </div>
    </dl>

    {#if !ro}
      <div class="edit">
        <StoreSelect
          value={receipt.shopping_location_id}
          suggestedName={receipt.store_name ?? ''}
          label="Which Grocy store is this?"
          emptyLabel="Choose a store"
          onchange={(id) => patch({ shopping_location_id: id })}
        />
        <label class="field">
          <span>Date of purchase</span>
          <input
            type="date"
            value={receipt.purchased_on ?? ''}
            onchange={(e) => patch({ purchased_on: e.currentTarget.value || null })}
          />
        </label>
      </div>
      {#if receipt.shopping_location_id == null}
        <p class="small muted">Choose it once; receipts from {receipt.store_name ? 'this shop' : 'the same shop'} are recognised from then on.</p>
      {/if}
    {/if}

    {#each receipt.warnings as w, i (i)}
      <div class="note warn"><Icon name="alert" size={18} /><p>{w}</p></div>
    {/each}

    {#if !ro}
      <div class="actions">
        <button type="button" class="btn small" onclick={() => (photosOpen = true)}><Icon name="eye" size={18} /> Photo</button>
        <button
          type="button"
          class="btn small"
          onclick={() => {
            nameDraft = receipt.store_name ?? '';
            editingName = !editingName;
          }}><Icon name="pencil" size={18} /> Rename</button
        >
        <button type="button" class="btn small" onclick={() => reread(false)}><Icon name="refresh" size={18} /> Read again</button>
        {#if store.trip?.ai_available}
          <button type="button" class="btn small" onclick={() => reread(true)}><Icon name="spark" size={18} /> Read with AI</button>
        {/if}
        <button type="button" class="btn small danger" onclick={() => (confirmDelete = true)}><Icon name="trash" size={18} /> Delete</button>
      </div>
    {/if}
  {/if}

  {#if confirmDelete}
    <div class="confirm note warn" role="alert">
      <p>Delete this receipt? Items matched to it keep their scans but lose the receipt's prices and amounts.</p>
      <div class="actions">
        <button type="button" class="btn small" onclick={() => (confirmDelete = false)}>Keep</button>
        <button type="button" class="btn small danger" onclick={remove}>Delete receipt</button>
      </div>
    </div>
  {/if}
</article>

<Sheet bind:open={photosOpen} title={title} wide>
  <div class="photos">
    {#each receipt.images as img, i (img.id)}
      <img src={img.url} alt="{title}, part {i + 1} of {receipt.images.length}" />
    {/each}
  </div>
</Sheet>

<style>
  .receipt {
    display: grid;
    gap: 14px;
    padding: 18px var(--gutter);
    background: var(--surface);
    border-bottom: 1px solid var(--line);
  }
  @media (min-width: 960px) {
    .receipt {
      border: 2px solid var(--line);
      border-radius: var(--r-lg);
    }
  }
  .receipt.failed {
    border-left: 6px solid var(--tomato);
  }
  header {
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .thumb {
    position: relative;
    flex: none;
    width: 56px;
    height: 72px;
    padding: 0;
    border: 0;
    border-radius: 10px;
    overflow: hidden;
    background: var(--surface-2);
    cursor: zoom-in;
  }
  .thumb img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
  .pages {
    position: absolute;
    right: 4px;
    bottom: 4px;
    min-width: 20px;
    padding: 0 5px;
    border-radius: 6px;
    background: var(--cobalt);
    color: var(--on-cobalt);
    font-size: 0.75rem;
    font-weight: 750;
  }
  .head-text {
    flex: 1;
    min-width: 0;
  }
  h3 {
    font-size: var(--fs-lg);
  }
  .name-form {
    display: flex;
    gap: 8px;
  }
  .reading {
    height: 6px;
    border-radius: 3px;
    background: var(--surface-2);
    overflow: hidden;
  }
  .reading span {
    display: block;
    width: 35%;
    height: 100%;
    border-radius: 3px;
    background: var(--cobalt);
    animation: sweep 1.4s ease-in-out infinite;
  }
  @keyframes sweep {
    from {
      transform: translateX(-100%);
    }
    to {
      transform: translateX(300%);
    }
  }
  .facts {
    display: grid;
    gap: 6px;
    margin: 0;
  }
  .facts div {
    display: grid;
    grid-template-columns: 6.5rem 1fr;
    gap: 10px;
  }
  dt {
    color: var(--ink-2);
    font-size: var(--fs-sm);
    padding-top: 2px;
  }
  dd {
    margin: 0;
    font-weight: 600;
  }
  .edit {
    display: grid;
    gap: 14px;
  }
  @media (min-width: 560px) {
    .edit {
      grid-template-columns: 1fr 1fr;
      align-items: end;
    }
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .confirm {
    display: grid;
  }
  .photos {
    display: grid;
    gap: 0;
  }
  .photos img {
    width: 100%;
    display: block;
  }
</style>
