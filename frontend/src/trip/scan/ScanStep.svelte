<script lang="ts">
  import { api, errorMessage } from '../../lib/api';
  import { beep, buzz, setSoundEnabled, soundEnabled } from '../../lib/feedback';
  import { navigate } from '../../lib/router.svelte';
  import { plural, qty } from '../../lib/format';
  import { toasts, viewport } from '../../lib/ui.svelte';
  import { tripIdFromLink } from '../../lib/triplink';
  import type { IdName, ItemOut } from '../../lib/types';
  import Icon from '../../components/Icon.svelte';
  import ProductPicker from '../../components/ProductPicker.svelte';
  import Viewfinder from './Viewfinder.svelte';
  import ManualEntry from './ManualEntry.svelte';
  import ScanRow from './ScanRow.svelte';
  import type { TripStore } from '../trip.svelte';

  let { store }: { store: TripStore } = $props();

  // A code still in view isn't counted again until it has been out of view this long.
  // Shorter when counting stock, where the next identical can is the point.
  const COOLDOWN_MS = 2500;
  const COUNTING_COOLDOWN_MS = 1200;

  type Last =
    | { kind: 'known' | 'new' | 'repeat'; item: ItemOut }
    | { kind: 'pending'; code: string }
    | { kind: 'error'; code: string; message: string };

  let last = $state<Last | null>(null);
  let flashKey = $state(0);
  let pending = $state<string[]>([]);
  let sound = $state(soundEnabled());
  let pickerOpen = $state(false);
  // Most recently touched first: item id -> order
  let touched = $state<Record<number, number>>({});
  let freshId = $state<number | null>(null);
  let touchSeq = 0;

  const seen = new Map<string, number>();
  const inflight = new Set<string>();

  const items = $derived(
    (store.trip?.items ?? [])
      .filter((i) => i.source === 'scan' || i.source === 'manual')
      .sort((a, b) => (touched[b.id] ?? 0) - (touched[a.id] ?? 0) || b.id - a.id),
  );
  const needCount = $derived(items.filter((i) => i.state === 'needs_product').length);
  const inventory = $derived(store.trip?.kind === 'inventory');

  function fromCamera(code: string) {
    const now = performance.now();
    const prev = seen.get(code);
    seen.set(code, now);
    // Ignore a code that's still in view; it counts again once it has left for a moment.
    if (prev !== undefined && now - prev < (inventory ? COUNTING_COOLDOWN_MS : COOLDOWN_MS)) return;
    void accept(code);
  }

  async function accept(raw: string) {
    const code = raw.trim();
    // The "use phone as scanner" code from another screen is a link, not a product.
    const linked = tripIdFromLink(code);
    if (linked !== null) {
      if (linked !== store.id) navigate(`/trips/${linked}/scan`);
      return;
    }
    if (!code || inflight.has(code) || store.readOnly) return;
    inflight.add(code);
    flashKey++;
    buzz(35);
    beep('ok');
    pending = [code, ...pending];
    last = { kind: 'pending', code };
    try {
      const res = await api.scan(store.id, code);
      store.mergeItem(res.item);
      store.touch();
      touched = { ...touched, [res.item.id]: ++touchSeq };
      freshId = res.item.id;
      last = {
        kind: res.duplicate ? 'repeat' : res.item.state === 'needs_product' ? 'new' : 'known',
        item: res.item,
      };
      if (res.item.state === 'needs_product' && !res.duplicate) beep('new');
    } catch (err) {
      const message = errorMessage(err);
      last = { kind: 'error', code, message };
      buzz([60, 60, 60]);
      beep('error');
      store.report(err);
    } finally {
      inflight.delete(code);
      pending = pending.filter((c) => c !== code);
    }
  }

  async function remove(item: ItemOut) {
    const ok = await store.run(() => api.deleteItem(store.id, item.id));
    if (ok) {
      seen.delete(item.barcode ?? '');
      if (last && 'item' in last && last.item.id === item.id) last = null;
      toasts.show(`Removed ${item.name}`);
    }
  }

  async function addWithoutBarcode(product: IdName) {
    const ok = await store.run(() => api.addItem(store.id, { product_id: product.id }));
    if (ok) toasts.success(`Added ${product.name}`);
  }

  function toggleSound() {
    sound = !sound;
    setSoundEnabled(sound);
    if (sound) beep('ok');
  }

  const lastText = $derived.by(() => {
    if (!last) return null;
    switch (last.kind) {
      case 'pending':
        return { tone: 'busy', text: `Looking up ${last.code}…` };
      case 'known':
        return { tone: 'ok', text: last.item.name };
      case 'repeat':
        return inventory
          ? { tone: 'ok', text: `${last.item.name}: ${qty(last.item.quantity)} counted` }
          : { tone: 'ok', text: `${last.item.name} again (scanned ${last.item.scan_count}×)` };
      case 'new':
        return {
          tone: 'new',
          text: last.item.lookup?.suggested_name
            ? `New: ${last.item.lookup.suggested_name}`
            : `New barcode ${last.item.barcode ?? ''}: needs a name`,
        };
      case 'error':
        return { tone: 'bad', text: last.message };
    }
  });
</script>

<div class="scan">
  <div class="capture">
    {#if store.readOnly}
      <div class="locked note">
        <Icon name="info" size={18} />
        <p>
          This {inventory ? 'inventory' : 'trip'} is already in Grocy. To scan more, undo it on the Review step, or start a new
          {inventory ? 'inventory' : 'trip'}.
        </p>
      </div>
    {:else}
      {#if !viewport.coarse}
        <button type="button" class="phone-hint" onclick={() => (store.linkOpen = true)}>
          <Icon name="phone" size={26} />
          <span>
            <strong>Scanning is easier with your phone.</strong>
            <span class="muted">Show a code to open this {inventory ? 'inventory' : 'trip'} there; what you scan appears here.</span>
          </span>
          <Icon name="forward" size={20} />
        </button>
      {/if}
      <Viewfinder ondetect={fromCamera} {flashKey}>
        {#snippet overlay()}
          {#if lastText}
            <div class="last {lastText.tone}" role="status" aria-live="polite">
              {#if lastText.tone === 'busy'}<span class="spinner"></span>{:else if lastText.tone === 'bad'}<Icon name="alert" size={20} />{:else if lastText.tone === 'new'}<Icon name="plus" size={20} />{:else}<Icon name="check" size={20} />{/if}
              <span>{lastText.text}</span>
            </div>
          {/if}
        {/snippet}
      </Viewfinder>
      <div class="tools">
        <ManualEntry onsubmit={(c) => accept(c)} />
        <div class="tool-row">
          <button type="button" class="btn ghost small" onclick={() => (pickerOpen = true)}>
            <Icon name="box" size={20} /> No barcode? Pick a product
          </button>
          <button type="button" class="btn ghost small icon" aria-pressed={sound} onclick={toggleSound} aria-label={sound ? 'Scan sound on' : 'Scan sound off'}>
            <Icon name={sound ? 'sound' : 'mute'} size={20} />
          </button>
        </div>
      </div>
    {/if}
  </div>

  <section class="list" aria-labelledby="scanned-h">
    <header class="list-head">
      <h2 id="scanned-h">{items.length ? plural(items.length, 'item') + ' scanned' : 'Nothing scanned yet'}</h2>
      {#if needCount}
        <span class="badge attention">{needCount} new</span>
      {/if}
    </header>
    {#if items.length === 0 && pending.length === 0}
      {#if inventory}
        <p class="muted empty">
          Scan every piece: scanning the same thing again counts one more. Or scan one and set the count with − and +.
          Turn the camera off while you walk to the next cupboard.
        </p>
      {:else}
        <p class="muted empty">Scan each product once. The receipt decides how many you bought, so there's no need to scan duplicates.</p>
      {/if}
    {/if}
    <ul>
      {#each pending as code (code)}
        <li class="pending small muted"><span class="spinner"></span> Looking up {code}…</li>
      {/each}
      {#each items as item (item.id)}
        <ScanRow
          {item}
          href={`/trips/${store.id}/review#item-${item.id}`}
          fresh={freshId === item.id}
          onremove={store.readOnly || item.state === 'committed' ? undefined : () => remove(item)}
          onquantity={inventory && !store.readOnly && item.state !== 'committed'
            ? (v) => store.run(() => api.patchItem(store.id, item.id, { quantity: v }))
            : undefined}
        />
      {/each}
    </ul>
    {#if items.length > 0 && !store.readOnly}
      <div class="next">
        {#if inventory}
          <button type="button" class="btn block" onclick={() => navigate(`/trips/${store.id}/review`, { replace: true })}>
            Done counting? Add due dates and review <Icon name="forward" size={20} />
          </button>
        {:else}
          <button type="button" class="btn block" onclick={() => navigate(`/trips/${store.id}/receipts`, { replace: true })}>
            Done scanning? Add the receipt <Icon name="forward" size={20} />
          </button>
        {/if}
      </div>
    {/if}
  </section>
</div>

<ProductPicker bind:open={pickerOpen} title="Add a product without a barcode" onpick={addWithoutBarcode} />

<style>
  .scan {
    display: grid;
  }
  .phone-hint {
    display: flex;
    align-items: center;
    gap: 14px;
    width: calc(100% - 32px);
    margin: 14px 16px;
    padding: 14px 16px;
    text-align: left;
    font: inherit;
    color: inherit;
    cursor: pointer;
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 16px;
  }
  .phone-hint > span {
    flex: 1;
    display: grid;
    gap: 2px;
  }
  .phone-hint:hover {
    border-color: var(--cobalt);
  }
  .tools {
    display: grid;
    gap: 6px;
    padding: 12px var(--gutter) 4px;
  }
  .tool-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .locked {
    margin: 16px var(--gutter) 0;
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
  .last.new {
    background: #f0b429;
    color: #2a1d00;
  }
  .last.bad {
    background: #c23328;
    color: #fff;
  }
  .list {
    padding: 8px var(--gutter) 0;
  }
  .list-head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 0 6px;
  }
  .list-head h2 {
    font-size: var(--fs-lg);
  }
  .empty {
    padding: 8px 0 16px;
    max-width: 52ch;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .pending {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 56px;
    padding: 0 8px;
    border-bottom: 1px solid var(--line);
  }
  .next {
    padding: 18px 0 8px;
  }
  @media (min-width: 960px) {
    .scan {
      grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
      gap: 32px;
      padding: 24px var(--gutter) 0;
      align-items: start;
    }
    .capture {
      position: sticky;
      top: calc(var(--safe-t) + 130px);
    }
    .tools {
      padding: 14px 0 0;
    }
    .list {
      padding: 0;
    }
    .list-head {
      padding-top: 0;
    }
  }
</style>
