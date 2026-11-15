<script lang="ts">
  import { api } from '../../lib/api';
  import { dueLabel, money, qty } from '../../lib/format';
  import type { ItemOut } from '../../lib/types';
  import Icon from '../../components/Icon.svelte';
  import QtyStepper from './QtyStepper.svelte';
  import ItemEditor from './ItemEditor.svelte';
  import ResolveProduct from './ResolveProduct.svelte';
  import type { TripStore } from '../trip.svelte';

  let {
    store,
    item,
    expanded = false,
    ontoggle,
  }: { store: TripStore; item: ItemOut; expanded?: boolean; ontoggle: () => void } = $props();

  const line = $derived(item.receipt_line_id != null ? store.lineById.get(item.receipt_line_id) : undefined);
  const needs = $derived(item.state === 'needs_product');
  const locked = $derived(store.readOnly || item.state === 'committed');
  const title = $derived(needs ? item.lookup?.suggested_name || line?.description || item.name : item.name);
</script>

<li id="item-{item.id}" class="item {item.state}" class:expanded class:warned={item.warnings.length > 0 && item.state === 'ready'}>
  <div class="top">
    <div class="name-col">
      <h3 class="name">
        {title}
        {#if item.new_product}<span class="tag new">New</span>{/if}
      </h3>
      {#if line}
        <p class="line small">
          <Icon name="receipt" size={15} />
          <span>{line.raw_text || line.description}</span>
        </p>
      {:else if item.barcode && needs}
        <p class="line small muted"><Icon name="barcode" size={15} /> <span>{item.barcode}</span></p>
      {/if}
    </div>
    <div class="price">
      {#if item.line_total != null}
        <span class="amount">{money(item.line_total)}</span>
      {:else}
        <span class="amount muted none">No price</span>
      {/if}
    </div>
  </div>

  {#if item.state === 'failed' && item.error}
    <div class="note bad"><Icon name="alert" size={18} /><p>Grocy said: {item.error}</p></div>
  {/if}

  {#if needs && !locked}
    <ResolveProduct {store} {item} />
  {:else}
    <div class="quick">
      {#if locked}
        <span class="amount-line">
          <strong>{qty(item.committed_amount ?? item.stock_amount)}</strong>
          {item.stock_unit}
        </span>
      {:else}
        <QtyStepper
          value={item.quantity}
          label="Amount of {title}"
          onchange={(v) => store.run(() => api.patchItem(store.id, item.id, { quantity: v }))}
        />
        <span class="pack small muted">
          {#if item.pack_factor !== 1}= {qty(item.stock_amount)} {item.stock_unit}{:else}{item.stock_unit}{/if}
        </span>
      {/if}
      <span class="due small" class:never={item.due_date === 'never'}>
        <Icon name="calendar" size={16} />
        {dueLabel(item.due_date)}
      </span>
    </div>
  {/if}

  {#if item.warnings.length && !locked}
    <ul class="warnings">
      {#each item.warnings as w, i (i)}
        <li><Icon name="alert" size={16} /> {w}</li>
      {/each}
    </ul>
  {/if}

  {#if !locked}
    <button type="button" class="more" aria-expanded={expanded} aria-controls="edit-{item.id}" onclick={ontoggle}>
      {expanded ? 'Close details' : needs ? 'More options' : 'Details and changes'}
      <span class="chev" class:up={expanded}><Icon name="down" size={18} /></span>
    </button>
    {#if expanded}
      <div id="edit-{item.id}">
        <ItemEditor {store} {item} />
      </div>
    {/if}
  {/if}
</li>

<style>
  .item {
    display: grid;
    gap: 12px;
    padding: 16px var(--gutter) 6px;
    background: var(--surface);
    border-bottom: 1px solid var(--line);
    scroll-margin-top: 140px;
  }
  @media (min-width: 960px) {
    .item {
      border: 2px solid var(--line);
      border-radius: var(--r-lg);
      padding-inline: 20px;
    }
  }
  .item.needs_product {
    border-left: 6px solid var(--saffron);
  }
  .item.failed {
    border-left: 6px solid var(--tomato);
  }
  .item.skipped {
    background: transparent;
  }
  .item.skipped .name {
    text-decoration: line-through;
    color: var(--ink-2);
  }
  .item.expanded {
    box-shadow: var(--shadow);
    position: relative;
    z-index: 1;
  }
  .top {
    display: flex;
    gap: 12px;
    align-items: flex-start;
  }
  .name-col {
    flex: 1;
    min-width: 0;
    display: grid;
    gap: 4px;
  }
  .name {
    font-size: var(--fs-lg);
    font-weight: 720;
    line-height: 1.2;
  }
  .tag {
    display: inline-block;
    vertical-align: 0.15em;
    margin-left: 6px;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 750;
    letter-spacing: 0.01em;
  }
  .tag.new {
    background: var(--cobalt-soft);
    color: var(--cobalt);
  }
  .line {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--ink-2);
    min-width: 0;
  }
  .line span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .line :global(svg) {
    flex: none;
    color: var(--ink-3);
  }
  .price {
    flex: none;
    text-align: right;
  }
  .amount {
    font-size: var(--fs-lg);
    font-weight: 760;
  }
  .amount.none {
    font-size: var(--fs-sm);
    font-weight: 600;
  }
  .quick {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 14px;
  }
  .pack {
    margin-left: -6px;
  }
  .amount-line strong {
    font-size: var(--fs-lg);
  }
  .due {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-left: auto;
    padding: 6px 10px;
    border-radius: 999px;
    background: var(--surface-2);
    color: var(--ink-2);
    font-weight: 650;
  }
  .warnings {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 4px;
  }
  .warnings li {
    display: flex;
    gap: 8px;
    align-items: flex-start;
    padding: 8px 10px;
    border-radius: var(--r-sm);
    background: var(--saffron-soft);
    color: var(--saffron-ink);
    font-size: var(--fs-sm);
    font-weight: 600;
  }
  .warnings :global(svg) {
    flex: none;
    margin-top: 2px;
  }
  .more {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    min-height: 44px;
    border: 0;
    background: none;
    color: var(--cobalt);
    font: inherit;
    font-size: var(--fs-sm);
    font-weight: 700;
    cursor: pointer;
    border-radius: var(--r-sm);
  }
  .more:hover {
    background: var(--cobalt-soft);
  }
  .chev {
    display: grid;
    transition: transform 160ms ease;
  }
  .chev.up {
    transform: rotate(180deg);
  }
</style>
