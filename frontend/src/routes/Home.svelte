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
  import JoinTrip from '../components/JoinTrip.svelte';

  let trips = $state<TripSummary[] | null>(null);
  let error = $state<string | null>(null);
  let starting = $state<TripKind | null>(null);
  let joinOpen = $state(false);

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
    <button type="button" class="btn ghost icon" aria-label="Join a trip open on another screen" title="Join a trip" onclick={() => (joinOpen = true)}>
      <Icon name="qr" />
    </button>
    <a class="btn ghost icon" href="/settings" aria-label="Settings"><Icon name="gear" /></a>
  {/snippet}
</TopBar>

<main class="page home">
  <section class="open" aria-labelledby="open-h">
    <div class="section-head">
      <h1 id="open-h">{open.length ? 'In progress' : 'Back from the shops?'}</h1>
      <div class="starts wide-only">
        <button type="button" class="btn" onclick={() => start('inventory')} disabled={starting !== null}>
          <Icon name="box" /> Take inventory
        </button>
        <button type="button" class="btn primary" onclick={() => start()} disabled={starting !== null}>
          <Icon name="plus" /> Start a shopping trip
        </button>
      </div>
    </div>

    {#if trips === null && !error}
      <div class="placeholder" aria-busy="true"></div>
    {:else if error}
      <div class="note bad"><Icon name="alert" size={18} /><p>{error} <button class="linklike" onclick={load}>Try again</button></p></div>
    {:else if open.length === 0}
      <ol class="how">
        <li><Icon name="barcode" /> <span><strong>Scan</strong> each thing you bought, once.</span></li>
        <li><Icon name="receipt" /> <span><strong>Photograph</strong> the receipt, or several if you went to more than one shop.</span></li>
        <li><Icon name="check" /> <span><strong>Check</strong> the list and add it all to Grocy with one tap.</span></li>
      </ol>
      <p class="inv-hint small muted">
        Setting up Grocy for the first time? <strong>Take inventory</strong> instead: scan what's already in the
        cupboards, with no receipt or prices needed.
      </p>
    {:else}
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
    {/if}
  </section>

  <p class="join">
    <button type="button" class="btn ghost small" onclick={() => (joinOpen = true)}>
      <Icon name="qr" size={20} /> Join a trip that's open on another screen
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

<JoinTrip bind:open={joinOpen} />

<div class="dock narrow-only">
  <button type="button" class="btn primary big block" onclick={() => start()} disabled={starting !== null}>
    {#if starting === 'shopping'}<span class="spinner"></span>{:else}<Icon name="plus" size={26} />{/if}
    Start a shopping trip
  </button>
  <button type="button" class="btn block" onclick={() => start('inventory')} disabled={starting !== null}>
    {#if starting === 'inventory'}<span class="spinner"></span>{:else}<Icon name="box" />{/if}
    Take inventory
  </button>
</div>

<style>
  .join {
    margin: 4px 0 0;
  }
  .starts {
    gap: 10px;
  }
  .inv-hint {
    margin-top: 12px;
    max-width: 60ch;
  }
  .open-trip.inventory {
    border-left-color: var(--basil);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    font-weight: 760;
    font-size: 1.125rem;
  }
  .home {
    padding-bottom: calc(var(--safe-b) + 180px);
    display: grid;
    gap: 36px;
    padding-top: 24px;
  }
  .section-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 18px;
  }
  .placeholder {
    height: 120px;
    border-radius: var(--r-lg);
    background: var(--surface-2);
  }
  .how {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 2px;
    border-radius: var(--r-lg);
    overflow: hidden;
  }
  .how li {
    display: flex;
    gap: 14px;
    align-items: flex-start;
    padding: 16px 18px;
    background: var(--surface);
    color: var(--ink-2);
  }
  .how li :global(svg) {
    color: var(--cobalt);
    margin-top: 1px;
  }
  .how strong {
    color: var(--ink);
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
  .history h2 {
    margin-bottom: 10px;
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
  .dock {
    display: grid;
    gap: 8px;
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    padding: 12px var(--gutter) calc(var(--safe-b) + 14px);
    background: linear-gradient(transparent, var(--paper) 30%);
  }
  .wide-only {
    display: none;
  }
  @media (min-width: 720px) {
    .wide-only {
      display: inline-flex;
    }
    .narrow-only {
      display: none;
    }
    .home {
      padding-bottom: 48px;
    }
  }
</style>
