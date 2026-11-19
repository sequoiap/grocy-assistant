<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage } from '../lib/api';
  import { navigate } from '../lib/router.svelte';
  import { money, plural, qty, shortDate, tripTitle, listJoin } from '../lib/format';
  import { toasts } from '../lib/ui.svelte';
  import type { TripKind, TripSummary } from '../lib/types';
  import Icon from '../components/Icon.svelte';
  import Mark from '../components/Mark.svelte';
  import TopBar from '../components/TopBar.svelte';
  import OtherDevices from '../components/devices/OtherDevices.svelte';

  let trips = $state<TripSummary[] | null>(null);
  let error = $state<string | null>(null);
  let starting = $state<TripKind | null>(null);
  let devicesOpen = $state(false);

  const open = $derived((trips ?? []).filter((t) => t.status === 'open'));
  const done = $derived((trips ?? []).filter((t) => t.status === 'submitted'));

  async function load() {
    try {
      trips = await api.trips();
      error = null;
    } catch (err) {
      error = errorMessage(err);
    }
  }

  onMount(() => {
    void load();
  });

  async function start(kind: TripKind = 'shopping') {
    starting = kind;
    try {
      const trip = await api.createTrip(kind);
      navigate(`/trips/${trip.id}/scan`);
    } catch (err) {
      toasts.error(errorMessage(err));
    } finally {
      starting = null;
    }
  }

  function summary(t: TripSummary): string {
    const parts = [plural(t.item_count, t.kind === 'inventory' ? 'product' : 'item')];
    if (t.committed_count && t.committed_count < t.item_count) parts.push(`${qty(t.committed_count)} already in Grocy`);
    if (t.receipt_count) parts.push(plural(t.receipt_count, 'receipt'));
    return parts.join(', ');
  }
</script>

<TopBar>
  {#snippet title()}
    <div class="brand"><Mark size={30} /> <span>Grocy Assistant</span></div>
  {/snippet}
  {#snippet end()}
    <button type="button" class="btn ghost icon" aria-label="Other devices" title="Other devices: open the app there, or join a trip" onclick={() => (devicesOpen = true)}>
      <Icon name="qr" />
    </button>
    <a class="btn ghost icon" href="/settings" aria-label="Settings"><Icon name="gear" /></a>
  {/snippet}
</TopBar>

<main class="page home">
  <section aria-labelledby="start-h">
    <h1 id="start-h" class="sr-only">Start something</h1>
    <div class="cards">
      <button type="button" class="card primary wide" onclick={() => start()} disabled={starting !== null}>
        <span class="c-icon">{#if starting === 'shopping'}<span class="spinner"></span>{:else}<Icon name="plus" size={26} />{/if}</span>
        <span class="c-title">Start a shopping trip</span>
        <span class="c-desc">Scan what you bought, snap the receipt, add it all to Grocy at once.</span>
      </button>
      <button type="button" class="card" onclick={() => start('inventory')} disabled={starting !== null}>
        <span class="c-icon">{#if starting === 'inventory'}<span class="spinner"></span>{:else}<Icon name="box" />{/if}</span>
        <span class="c-title">Take inventory</span>
        <span class="c-desc">Count what's already at home. No receipt needed.</span>
      </button>
      <a class="card" href="/consume">
        <span class="c-icon"><Icon name="bowl" /></span>
        <span class="c-title">Consume or open</span>
        <span class="c-desc">Used something up or opened it? Scan it or find it by name.</span>
      </a>
    </div>
  </section>

  {#if trips === null && !error}
    <div class="placeholder" aria-busy="true"></div>
  {:else if error}
    <div class="note bad"><Icon name="alert" size={18} /><p>{error} <button class="linklike" onclick={load}>Try again</button></p></div>
  {:else if open.length}
    <section class="open" aria-labelledby="open-h">
      <h2 id="open-h">In progress</h2>
      <ul class="open-list">
        {#each open as t (t.id)}
          <li>
            <a class="open-trip" class:inventory={t.kind === 'inventory'} href={`/trips/${t.id}`}>
              <span class="ot-title">{tripTitle(t)}</span>
              <span class="ot-meta">
                {summary(t)}{#if t.stores.length}, from {listJoin(t.stores)}{/if}
              </span>
              <span class="ot-by small muted">Started by {t.created_by}</span>
              <span class="ot-go" aria-hidden="true"><Icon name="forward" /></span>
            </a>
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  <p class="join">
    <button type="button" class="btn ghost small" onclick={() => (devicesOpen = true)}>
      <Icon name="qr" size={20} /> Open the app on another device, or join a trip from one
    </button>
  </p>

  {#if done.length}
    <section class="history" aria-labelledby="hist-h">
      <h2 id="hist-h">Added to Grocy</h2>
      <ul>
        {#each done as t (t.id)}
          <li>
            <a href={`/trips/${t.id}/review`} class="hist-row">
              <span class="h-date">{shortDate(t.submitted_at ?? t.created_at)}</span>
              <span class="h-main">
                <span class="h-stores">{t.kind !== 'inventory' && t.stores.length ? listJoin(t.stores) : tripTitle(t)}</span>
                <span class="small muted">{plural(t.item_count, 'item')}, by {t.created_by}</span>
              </span>
              <span class="h-total">{money(t.total)}</span>
            </a>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
</main>

<OtherDevices bind:open={devicesOpen} />

<style>
  .join {
    margin: -12px 0 0;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    font-weight: 760;
    font-size: 1.125rem;
  }
  .home {
    display: grid;
    gap: 32px;
    padding-top: 20px;
  }
  /* What can be started from here. One card per feature; more just flow on. */
  .cards {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
  .card {
    appearance: none;
    display: grid;
    grid-template-columns: 1fr;
    grid-template-areas:
      'icon'
      'title'
      'desc';
    justify-items: start;
    align-content: start;
    gap: 8px 12px;
    padding: 16px;
    border: 2px solid var(--line);
    border-radius: var(--r-lg);
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    text-align: left;
    text-decoration: none;
    cursor: pointer;
    touch-action: manipulation;
    transition:
      border-color 120ms ease,
      transform 80ms ease;
  }
  .card:hover:not(:disabled) {
    border-color: var(--cobalt);
  }
  .card:active:not(:disabled) {
    transform: translateY(2px);
  }
  .card:disabled {
    opacity: 0.6;
    cursor: progress;
  }
  /* Full width on phones, with room for the icon beside the title. */
  .card.wide {
    grid-column: 1 / -1;
    grid-template-columns: auto 1fr;
    grid-template-areas:
      'icon title'
      'desc desc';
    align-items: center;
  }
  .c-icon {
    grid-area: icon;
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border-radius: 14px;
    background: var(--cobalt-soft);
    color: var(--cobalt);
  }
  .c-title {
    grid-area: title;
    font-size: var(--fs-lg);
    font-weight: 760;
    line-height: 1.2;
    overflow-wrap: normal;
  }
  .c-desc {
    grid-area: desc;
    font-size: var(--fs-sm);
    color: var(--ink-2);
  }
  .card.primary {
    background: var(--cobalt);
    border-color: var(--cobalt);
    color: var(--on-cobalt);
    box-shadow: var(--lip);
  }
  .card.primary:hover:not(:disabled) {
    background: var(--cobalt-deep);
    border-color: var(--cobalt-deep);
  }
  .card.primary .c-icon {
    background: color-mix(in srgb, var(--on-cobalt) 18%, transparent);
    color: var(--on-cobalt);
  }
  .card.primary .c-desc {
    color: color-mix(in srgb, var(--on-cobalt) 85%, transparent);
  }
  .open h2,
  .history h2 {
    margin-bottom: 12px;
  }
  .placeholder {
    height: 120px;
    border-radius: var(--r-lg);
    background: var(--surface-2);
  }
  .open-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 12px;
  }
  .open-trip {
    position: relative;
    display: grid;
    gap: 4px;
    padding: 18px 56px 18px 20px;
    border-radius: var(--r-lg);
    background: var(--surface);
    border: 2px solid var(--line);
    border-left: 8px solid var(--cobalt);
    color: var(--ink);
    text-decoration: none;
  }
  .open-trip.inventory {
    border-left-color: var(--basil);
  }
  .open-trip:hover {
    border-color: var(--cobalt);
  }
  .ot-title {
    font-size: var(--fs-lg);
    font-weight: 750;
    line-height: 1.2;
  }
  .ot-go {
    position: absolute;
    right: 16px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--cobalt);
  }
  .history ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .hist-row {
    display: grid;
    grid-template-columns: 4.2rem 1fr auto;
    align-items: center;
    gap: 12px;
    min-height: 64px;
    padding: 10px 4px;
    border-bottom: 1px solid var(--line);
    color: var(--ink);
    text-decoration: none;
  }
  .hist-row:hover .h-stores {
    color: var(--cobalt);
  }
  .h-date {
    font-weight: 700;
    color: var(--ink-2);
  }
  .h-main {
    display: grid;
    min-width: 0;
  }
  .h-stores {
    font-weight: 650;
  }
  .h-total {
    font-weight: 700;
  }
  @media (min-width: 720px) {
    .home {
      padding-top: 28px;
      padding-bottom: 48px;
    }
    .cards {
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    }
    .card.wide {
      grid-column: auto;
      grid-template-columns: 1fr;
      grid-template-areas:
        'icon'
        'title'
        'desc';
      align-items: start;
    }
    .card {
      padding: 20px;
    }
  }
</style>
