<script lang="ts">
  import Icon from '../../components/Icon.svelte';
  import type { ItemOut } from '../../lib/types';

  let {
    item,
    href,
    fresh = false,
    onremove,
  }: { item: ItemOut; href: string; fresh?: boolean; onremove?: () => void } = $props();

  let imgFailed = $state(false);
  const needs = $derived(item.state === 'needs_product');
  const image = $derived(item.lookup?.image_url && !imgFailed ? item.lookup.image_url : null);
  const displayName = $derived(
    needs ? item.lookup?.suggested_name || 'Unknown product' : item.name,
  );
</script>

<li class="row" class:needs class:fresh>
  <span class="thumb" aria-hidden="true">
    {#if image}
      <img src={image} alt="" loading="lazy" referrerpolicy="no-referrer" onerror={() => (imgFailed = true)} />
    {:else if needs}
      <Icon name="barcode" />
    {:else}
      <Icon name="check" />
    {/if}
  </span>
  <a class="main" {href}>
    <span class="name">{displayName}</span>
    <span class="sub small">
      {#if needs}
        <span class="tag">New: needs a name</span>
      {:else if item.state === 'committed'}
        In Grocy
      {:else if item.new_product}
        New product
      {:else if item.state === 'skipped'}
        Skipped
      {:else}
        Known product
      {/if}
      {#if item.barcode}<span class="code">{item.barcode}</span>{/if}
    </span>
  </a>
  {#if item.scan_count > 1}
    <span class="count" title="Scanned {item.scan_count} times">×{item.scan_count}</span>
  {/if}
  {#if onremove}
    <button type="button" class="btn ghost icon remove" aria-label="Remove {displayName}" onclick={onremove}>
      <Icon name="x" size={20} />
    </button>
  {/if}
</li>

<style>
  .row {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 68px;
    padding: 8px 4px 8px 8px;
    border-bottom: 1px solid var(--line);
  }
  .fresh {
    animation: arrive 900ms ease-out;
  }
  @keyframes arrive {
    from {
      background: var(--saffron-soft);
    }
  }
  .thumb {
    flex: none;
    display: grid;
    place-items: center;
    width: 46px;
    height: 46px;
    border-radius: 12px;
    background: var(--basil-soft);
    color: var(--basil);
    overflow: hidden;
  }
  .needs .thumb {
    background: var(--saffron-soft);
    color: var(--saffron-ink);
  }
  .thumb img {
    width: 100%;
    height: 100%;
    object-fit: contain;
    background: #fff;
  }
  .main {
    flex: 1;
    min-width: 0;
    display: grid;
    gap: 2px;
    color: inherit;
    text-decoration: none;
  }
  .name {
    font-weight: 700;
    line-height: 1.25;
  }
  .main:hover .name {
    color: var(--cobalt);
  }
  .sub {
    display: flex;
    flex-wrap: wrap;
    gap: 2px 10px;
    color: var(--ink-2);
  }
  .tag {
    color: var(--saffron-ink);
    font-weight: 700;
  }
  .code {
    color: var(--ink-3);
    letter-spacing: 0.03em;
  }
  .count {
    flex: none;
    padding: 4px 10px;
    border-radius: 999px;
    background: var(--cobalt-soft);
    color: var(--cobalt);
    font-weight: 750;
  }
  .remove {
    color: var(--ink-3);
  }
</style>
