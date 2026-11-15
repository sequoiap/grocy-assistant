<script lang="ts">
  // What happened when the trip was added to Grocy.
  import { plural } from '../../lib/format';
  import type { SubmitResult } from '../../lib/types';
  import Icon from '../../components/Icon.svelte';
  import type { TripStore } from '../trip.svelte';

  let {
    store,
    result,
    onretry,
    onundo,
    onclose,
  }: {
    store: TripStore;
    result: SubmitResult;
    onretry: () => void;
    onundo: () => void;
    onclose: () => void;
  } = $props();

  const failedItems = $derived((store.trip?.items ?? []).filter((i) => i.state === 'failed'));
  const allDone = $derived(result.trip.status === 'submitted');
</script>

<section id="outcome" class="outcome" class:bad={result.failed > 0} aria-live="polite">
  <div class="head">
    <span class="mark"><Icon name={result.failed ? 'alert' : 'check'} size={28} /></span>
    <div>
      <h2>
        {#if result.committed && !result.failed}
          Added {plural(result.committed, 'item')} to Grocy
        {:else if result.committed}
          Added {result.committed}, {result.failed} didn't go through
        {:else if result.failed}
          {plural(result.failed, 'item')} couldn't be added
        {:else}
          Nothing new was added
        {/if}
      </h2>
      {#if allDone}
        <p class="small">The trip is done. Undo puts everything back the way it was.</p>
      {:else if result.remaining > 0}
        <p class="small">{plural(result.remaining, 'item')} still {result.remaining === 1 ? 'needs' : 'need'} a decision and {result.remaining === 1 ? 'is' : 'are'} waiting below.</p>
      {/if}
    </div>
    <button type="button" class="btn ghost icon" aria-label="Dismiss" onclick={onclose}><Icon name="x" /></button>
  </div>

  {#if failedItems.length}
    <ul class="fails">
      {#each failedItems as i (i.id)}
        <li><strong>{i.name}</strong>: {i.error ?? 'unknown error'}</li>
      {/each}
    </ul>
  {/if}

  <div class="actions">
    {#if result.failed}
      <button type="button" class="btn primary" onclick={onretry}><Icon name="refresh" size={20} /> Try again</button>
    {/if}
    {#if store.counts.committed > 0}
      <button type="button" class="btn" onclick={onundo}><Icon name="undo" size={20} /> Undo</button>
    {/if}
    {#if allDone}
      <a class="btn" href="/">Back to trips</a>
    {/if}
  </div>
</section>

<style>
  .outcome {
    display: grid;
    gap: 12px;
    margin: 14px var(--gutter) 0;
    padding: 16px;
    border-radius: var(--r-lg);
    background: var(--basil-soft);
    color: var(--ink);
    scroll-margin-top: 140px;
  }
  .outcome.bad {
    background: var(--tomato-soft);
  }
  @media (min-width: 960px) {
    .outcome {
      margin-inline: 0;
    }
  }
  .head {
    display: flex;
    align-items: flex-start;
    gap: 12px;
  }
  .head > div {
    flex: 1;
  }
  .mark {
    color: var(--basil);
    display: grid;
  }
  .bad .mark {
    color: var(--tomato);
  }
  h2 {
    font-size: var(--fs-lg);
  }
  .head p {
    margin-top: 4px;
    color: var(--ink-2);
  }
  .fails {
    margin: 0;
    padding-left: 1.2em;
    display: grid;
    gap: 4px;
    font-size: var(--fs-sm);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
</style>
