<script lang="ts" module>
  // Scan or search, remembered for as long as the app is open.
  let lastMode: 'scan' | 'search' = 'scan';
</script>

<script lang="ts">
  // Consume or open what's already at home: scan its barcode, or find it by name
  // when the packaging is long gone. Everything goes straight to Grocy.
  import { onMount } from 'svelte';
  import { api, errorMessage } from '../lib/api';
  import { beep, buzz } from '../lib/feedback';
  import { back } from '../lib/router.svelte';
  import { toasts, reportError, viewport } from '../lib/ui.svelte';
  import type { StockActionOut, StockProduct } from '../lib/types';
  import Icon from '../components/Icon.svelte';
  import TopBar from '../components/TopBar.svelte';
  import Viewfinder from '../trip/scan/Viewfinder.svelte';
  import ManualEntry from '../trip/scan/ManualEntry.svelte';
  import ConsumeSheet from './ConsumeSheet.svelte';
  import { amountText, dueSoon, dueText, matches, stockText, tidy, type StockAction } from './stock';

  // A code still in view isn't looked up again until it has been out of view this long.
  const COOLDOWN_MS = 2000;

  type Last = { kind: 'pending'; code: string } | { kind: 'ok'; text: string } | { kind: 'error'; text: string };
  interface Done {
    key: number;
    text: string;
    transactionId: string | null;
    undone: boolean;
    undoing: boolean;
  }

  let mode = $state<'scan' | 'search'>(lastMode);
  let stock = $state<StockProduct[] | null>(null);
  let loadError = $state<string | null>(null);
  let query = $state('');
  let selected = $state<StockProduct | null>(null);
  let selectedCode: string | null = null;
  let amount = $state(1);
  let last = $state<Last | null>(null);
  let flashKey = $state(0);
  let done = $state<Done[]>([]);
  let doneSeq = 0;

  const seen = new Map<string, number>();
  const inflight = new Set<string>();

  const showCamera = $derived(viewport.wide || mode === 'scan');
  const showSearch = $derived(viewport.wide || mode === 'search');
  const hits = $derived((stock ?? []).filter((p) => matches(p, query)));

  $effect(() => {
    lastMode = mode;
  });

  async function load() {
    try {
      stock = await api.stock();
      loadError = null;
    } catch (err) {
      loadError = errorMessage(err);
    }
  }

  onMount(() => {
    void load();
  });

  function choose(p: StockProduct, code: string | null = null) {
    selectedCode = code;
    amount = Math.min(p.quick_consume_amount || 1, p.amount) || 1;
    selected = p;
  }

  function fromCamera(code: string) {
    const now = performance.now();
    const prev = seen.get(code);
    seen.set(code, now);
    if (prev !== undefined && now - prev < COOLDOWN_MS) return;
    void accept(code);
  }

  async function accept(raw: string) {
    const code = raw.trim();
    if (!code || inflight.has(code)) return;
    if (selected) {
      // Scanning the same thing again while it's open counts one more of it.
      if (code === selectedCode && amount < selected.amount) {
        amount = Math.min(selected.amount, tidy(amount + 1));
        flashKey++;
        buzz(35);
        beep('repeat');
      }
      return;
    }
    inflight.add(code);
    flashKey++;
    buzz(35);
    beep('ok');
    last = { kind: 'pending', code };
    try {
      const p = await api.stockScan(code);
      last = { kind: 'ok', text: `${p.name}: ${stockText(p).toLowerCase()}` };
      // Something was picked meanwhile (from the list, or a quicker scan): never swap
      // the product under someone's thumb.
      if (!selected) choose(p, code);
    } catch (err) {
      last = { kind: 'error', text: errorMessage(err) };
      buzz([60, 60, 60]);
      beep('error');
    } finally {
      inflight.delete(code);
    }
  }

  function describe(action: StockAction, n: number, spoiled: boolean, p: StockProduct): string {
    const verb = action === 'open' ? 'Opened' : spoiled ? 'Threw out' : 'Consumed';
    return `${verb} ${amountText(p, n)} of ${p.name}`;
  }

  function onDone(action: StockAction, n: number, spoiled: boolean, result: StockActionOut) {
    const p = result.product;
    const entry: Done = {
      key: ++doneSeq,
      text: describe(action, n, spoiled, p),
      transactionId: result.transaction_id,
      undone: false,
      undoing: false,
    };
    const { transactionId, text } = entry;
    // The toast carries what it needs to undo, so it works after its row has left the list.
    const toast = toasts.success(
      text,
      transactionId ? { label: 'Undo', run: () => void undo(transactionId, text) } : undefined,
    );
    if (transactionId) toastFor.set(transactionId, toast);
    // Only the last few: older ones can still be undone in Grocy's stock journal.
    done = [entry, ...done].slice(0, 3);
    last = null;
    patchStock(p);
    // Then the whole list: consuming a parent product can use up its sub-products' stock.
    void load();
  }

  /** Puts a product's new amounts into the list without reloading all of it. */
  function patchStock(p: StockProduct) {
    if (!stock) return;
    const rest = stock.filter((s) => s.id !== p.id);
    if (p.amount <= 0) stock = rest;
    else
      stock = [...rest, { ...p, pack_amount: null, stock_entry_id: null }].sort((a, b) =>
        a.name.toLowerCase().localeCompare(b.name.toLowerCase()),
      );
  }

  // Transactions undone or being undone, whether from a row or a toast.
  const undoing = new Set<string>();
  // The confirmation toast of each transaction, to take away once it's undone.
  const toastFor = new Map<string, number>();

  async function undo(transactionId: string, text: string) {
    if (undoing.has(transactionId)) return;
    undoing.add(transactionId);
    const entry = () => done.find((d) => d.transactionId === transactionId);
    const row = entry();
    if (row) row.undoing = true;
    try {
      await api.undoStock(transactionId);
      const now = entry();
      if (now) now.undone = true;
      const toast = toastFor.get(transactionId);
      if (toast !== undefined) toasts.dismiss(toast);
      toasts.show(`Undone: ${text}`);
      void load();
    } catch (err) {
      undoing.delete(transactionId);
      reportError(err);
    } finally {
      const now = entry();
      if (now) now.undoing = false;
    }
  }

  const lastTone = $derived(last?.kind === 'pending' ? 'busy' : last?.kind === 'error' ? 'bad' : 'ok');
</script>

<div style="--topbar-max: 1200px">
  <TopBar>
    {#snippet start()}
      <button type="button" class="btn ghost icon" aria-label="Back" onclick={() => back('/')}><Icon name="back" /></button>
    {/snippet}
    {#snippet title()}
      <h1 class="title">Consume or open</h1>
    {/snippet}
  </TopBar>

  <main class="consume">
    <div class="modes narrow-only" role="tablist" aria-label="Find a product by">
      <button type="button" role="tab" aria-selected={mode === 'scan'} class:on={mode === 'scan'} onclick={() => (mode = 'scan')}>
        <Icon name="barcode" size={20} /> Scan
      </button>
      <button type="button" role="tab" aria-selected={mode === 'search'} class:on={mode === 'search'} onclick={() => (mode = 'search')}>
        <Icon name="search" size={20} /> Search
      </button>
    </div>

    {#if showCamera}
      <div class="capture">
        <Viewfinder
          ondetect={fromCamera}
          {flashKey}
          hint="Point the camera at the barcode of what you're using up, or at a Grocy label."
        >
          {#snippet overlay()}
            {#if last}
              <div class="last {lastTone}" role="status" aria-live="polite">
                {#if last.kind === 'pending'}<span class="spinner"></span><span>Looking up {last.code}…</span>
                {:else if last.kind === 'error'}<Icon name="alert" size={20} /><span>{last.text}</span>
                {:else}<Icon name="check" size={20} /><span>{last.text}</span>{/if}
              </div>
            {/if}
          {/snippet}
        </Viewfinder>
        <div class="tools">
          <ManualEntry onsubmit={(c) => accept(c)} />
          <button type="button" class="btn ghost small narrow-only" onclick={() => (mode = 'search')}>
            <Icon name="search" size={20} /> No barcode? Search by name
          </button>
        </div>
      </div>
    {/if}

    <div class="side">
      {#if done.length}
        <section class="done" aria-labelledby="done-h">
          <h2 id="done-h">Just now</h2>
          <ul>
            {#each done as d (d.key)}
              <li class:undone={d.undone}>
                <Icon name={d.undone ? 'undo' : 'check'} size={18} />
                <span class="d-text">{d.undone ? `Undone: ${d.text}` : d.text}</span>
                {#if d.transactionId && !d.undone}
                  <button type="button" class="btn ghost small" disabled={d.undoing} onclick={() => d.transactionId && undo(d.transactionId, d.text)}>
                    {#if d.undoing}<span class="spinner"></span>{/if} Undo
                  </button>
                {/if}
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      {#if showSearch}
        <section class="search-panel" aria-labelledby="stock-h">
          <h2 id="stock-h" class="sr-only">In stock</h2>
          <label class="search">
            <span class="sr-only">Search what's in stock</span>
            <Icon name="search" />
            <!-- svelte-ignore a11y_autofocus -->
            <input
              bind:value={query}
              type="search"
              placeholder="Search what's in stock"
              autocomplete="off"
              enterkeyhint="search"
              autofocus={mode === 'search' && !viewport.wide}
            />
          </label>
          {#if stock === null && !loadError}
            <div class="placeholder" aria-busy="true"></div>
          {:else if loadError}
            <div class="note bad"><Icon name="alert" size={18} /><p>{loadError} <button class="linklike" onclick={load}>Try again</button></p></div>
          {:else if stock && stock.length === 0}
            <p class="muted empty">Grocy has nothing in stock right now.</p>
          {:else}
            <ul class="results" aria-label="In stock">
              {#each hits as p (p.id)}
                {@const due = dueText(p)}
                <li>
                  <button type="button" onclick={() => choose(p)}>
                    <span class="r-name">{p.name}</span>
                    <span class="r-meta small">
                      <span>{stockText(p)}</span>
                      {#if due}<span class:soon={dueSoon(p)}>{due}</span>{/if}
                    </span>
                    <span class="r-go" aria-hidden="true"><Icon name="forward" size={20} /></span>
                  </button>
                </li>
              {:else}
                <li class="empty muted">
                  Nothing in stock matches “{query.trim()}”. If it's there anyway, scan it, or add it to Grocy with
                  <strong>Take inventory</strong>.
                </li>
              {/each}
            </ul>
          {/if}
        </section>
      {/if}
    </div>
  </main>
</div>

<ConsumeSheet bind:product={selected} bind:amount ondone={onDone} />

<style>
  .title {
    font-size: var(--fs-lg);
  }
  .consume {
    display: grid;
    align-content: start;
    padding-bottom: calc(var(--safe-b) + 32px);
  }
  .modes {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
    margin: 12px var(--gutter);
    padding: 5px;
    border-radius: var(--r-md);
    background: var(--surface-2);
  }
  .modes button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 44px;
    border: 0;
    border-radius: var(--r-sm);
    background: transparent;
    color: var(--ink-2);
    font: inherit;
    font-weight: 700;
    cursor: pointer;
  }
  .modes button.on {
    background: var(--surface);
    color: var(--cobalt);
    box-shadow: var(--shadow);
  }
  .tools {
    display: grid;
    gap: 6px;
    padding: 12px var(--gutter) 4px;
    justify-items: start;
  }
  .tools :global(form) {
    width: 100%;
  }
  .last {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.95);
    color: #121c3a;
    font-weight: 700;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.3);
  }
  .last span:last-child {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .last.ok :global(svg) {
    color: #237a4b;
  }
  .last.bad {
    background: #c23328;
    color: #fff;
  }
  .side {
    display: grid;
    gap: 20px;
    padding: 8px var(--gutter) 0;
    align-content: start;
  }
  .done h2 {
    font-size: var(--fs-lg);
    margin-bottom: 4px;
  }
  .done ul,
  .results {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .done li {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 52px;
    border-bottom: 1px solid var(--line);
    color: var(--basil);
  }
  .done li.undone {
    color: var(--ink-3);
  }
  .d-text {
    flex: 1;
    min-width: 0;
    color: var(--ink);
    font-weight: 600;
  }
  .undone .d-text {
    color: var(--ink-3);
    font-weight: 400;
  }
  .search-panel {
    display: grid;
    gap: 10px;
  }
  .search {
    position: sticky;
    top: calc(var(--safe-t) + 61px);
    z-index: 5;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 14px;
    border: 2px solid var(--line);
    border-radius: var(--r-md);
    background: var(--surface);
    color: var(--ink-3);
  }
  .search:focus-within {
    border-color: var(--cobalt);
  }
  .search input {
    border: 0 !important;
    box-shadow: none !important;
    padding-inline: 0 !important;
    background: transparent !important;
  }
  .results button {
    position: relative;
    display: grid;
    gap: 2px;
    width: 100%;
    min-height: 64px;
    padding: 10px 40px 10px 6px;
    border: 0;
    border-bottom: 1px solid var(--line);
    background: none;
    color: var(--ink);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .results button:hover,
  .results button:focus-visible {
    background: var(--cobalt-soft);
  }
  .r-name {
    font-weight: 700;
    line-height: 1.25;
  }
  .r-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 2px 12px;
    color: var(--ink-2);
  }
  .soon {
    color: var(--tomato);
    font-weight: 700;
  }
  .r-go {
    position: absolute;
    right: 8px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--cobalt);
  }
  .empty {
    padding: 12px 6px;
    max-width: 52ch;
  }
  .placeholder {
    height: 160px;
    border-radius: var(--r-lg);
    background: var(--surface-2);
  }
  @media (min-width: 960px) {
    .narrow-only {
      display: none;
    }
    .consume {
      grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
      gap: 32px;
      max-width: 1200px;
      margin: 0 auto;
      padding: 24px var(--gutter) 48px;
      align-items: start;
    }
    .capture {
      position: sticky;
      top: calc(var(--safe-t) + 84px);
    }
    .tools {
      padding: 14px 0 0;
    }
    .side {
      padding: 0;
    }
  }
</style>
