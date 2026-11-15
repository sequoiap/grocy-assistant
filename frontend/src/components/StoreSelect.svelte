<script lang="ts">
  // Pick a Grocy store, or add a new one to Grocy inline.
  import { api } from '../lib/api';
  import { meta } from '../lib/session.svelte';
  import { reportError, toasts } from '../lib/ui.svelte';

  let {
    value,
    suggestedName = '',
    label = 'Store in Grocy',
    emptyLabel = 'Not set',
    onchange,
    disabled = false,
  }: {
    value: number | null;
    suggestedName?: string;
    label?: string;
    emptyLabel?: string;
    onchange: (id: number | null) => void;
    disabled?: boolean;
  } = $props();

  const uid = $props.id();
  let adding = $state(false);
  let newName = $state('');
  let busy = $state(false);

  const stores = $derived(meta.value?.stores ?? []);

  function onSelect(e: Event) {
    const v = (e.currentTarget as HTMLSelectElement).value;
    if (v === '__add') {
      adding = true;
      newName = suggestedName ? titleCase(suggestedName) : '';
      (e.currentTarget as HTMLSelectElement).value = value == null ? '' : String(value);
      return;
    }
    onchange(v === '' ? null : Number(v));
  }

  function titleCase(s: string): string {
    // Receipts shout ("WALMART SUPERCENTER"); suggest a friendlier name.
    return s === s.toUpperCase() ? s.toLowerCase().replace(/\b\p{L}/gu, (c) => c.toUpperCase()) : s;
  }

  async function create(e: SubmitEvent) {
    e.preventDefault();
    const name = newName.trim();
    if (!name) return;
    busy = true;
    try {
      const store = await api.createStore(name);
      await meta.load(true);
      adding = false;
      toasts.success(`Added ${store.name} to Grocy`);
      onchange(store.id);
    } catch (err) {
      reportError(err);
    } finally {
      busy = false;
    }
  }
</script>

<div class="store-select">
  <label class="field" for="{uid}-sel">
    <span>{label}</span>
  </label>
  {#if !adding}
    <select id="{uid}-sel" value={value == null ? '' : String(value)} onchange={onSelect} {disabled}>
      <option value="">{emptyLabel}</option>
      {#each stores as s (s.id)}
        <option value={String(s.id)}>{s.name}</option>
      {/each}
      <option value="__add">+ Add a new store to Grocy…</option>
    </select>
  {:else}
    <form class="add" onsubmit={create}>
      <input id="{uid}-sel" bind:value={newName} placeholder="Store name" maxlength="120" aria-label="New store name" />
      <div class="add-actions">
        <button type="button" class="btn small" onclick={() => (adding = false)}>Cancel</button>
        <button class="btn small primary" disabled={busy || !newName.trim()}>
          {#if busy}<span class="spinner"></span>{/if} Add to Grocy
        </button>
      </div>
    </form>
  {/if}
</div>

<style>
  .store-select {
    display: grid;
    gap: 6px;
  }
  .add {
    display: grid;
    gap: 8px;
  }
  .add-actions {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
  }
</style>
