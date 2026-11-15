<script lang="ts">
  import { navigate } from '../../lib/router.svelte';
  import Icon from '../../components/Icon.svelte';
  import ReceiptComposer from './ReceiptComposer.svelte';
  import ReceiptCard from './ReceiptCard.svelte';
  import type { TripStore } from '../trip.svelte';

  let { store }: { store: TripStore } = $props();

  const receipts = $derived(store.trip?.receipts ?? []);
  const anyReady = $derived(receipts.some((r) => r.status === 'ready'));
</script>

<div class="receipts">
  <div class="side">
    {#if !store.readOnly}
      <ReceiptComposer {store} hasReceipts={receipts.length > 0} />
    {/if}
    <p class="why small muted">
      The receipt fills in how many you bought and what you paid, so each product only needs scanning once.
      Things without a barcode, like fruit or deli, can be added from the receipt on the Review step.
    </p>
  </div>

  <section class="list" aria-label="Receipts">
    {#if receipts.length === 0}
      <p class="empty muted">No receipts yet. Shopped at more than one place? Add each shop's receipt separately.</p>
    {:else}
      {#each [...receipts].reverse() as r (r.id)}
        <ReceiptCard {store} receipt={r} index={receipts.indexOf(r)} />
      {/each}
    {/if}
    {#if anyReady || store.counts.scanned > 0}
      <div class="next">
        <button type="button" class="btn block" onclick={() => navigate(`/trips/${store.id}/review`, { replace: true })}>
          {store.trip?.processing ? 'Review while it reads' : 'Review everything'} <Icon name="forward" size={20} />
        </button>
      </div>
    {/if}
  </section>
</div>

<style>
  .receipts {
    display: grid;
  }
  .why {
    padding: 14px var(--gutter) 6px;
    max-width: 60ch;
  }
  .empty {
    padding: 20px var(--gutter);
  }
  .next {
    padding: 18px var(--gutter);
  }
  @media (min-width: 960px) {
    .receipts {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr);
      gap: 32px;
      padding: 24px var(--gutter) 0;
      align-items: start;
    }
    .side {
      position: sticky;
      top: calc(var(--safe-t) + 130px);
    }
    .why {
      padding-inline: 4px;
    }
    .list {
      display: grid;
      gap: 16px;
    }
    .empty,
    .next {
      padding-inline: 0;
      padding-top: 0;
    }
  }
</style>
