<script lang="ts">
  // The few things Grocy needs to create a product. Defaults come from Grocy's own presets.
  import { meta } from '../../lib/session.svelte';
  import type { NewProductDraft } from '../../lib/types';

  let {
    initial,
    submitLabel = 'Create product',
    busy = false,
    error = null,
    calm = false,
    onsubmit,
    oncancel,
  }: {
    initial: Partial<NewProductDraft> & { name: string };
    submitLabel?: string;
    busy?: boolean;
    error?: string | null;
    /** The message isn't a mistake to fix (Grocy is unreachable): show it without the alarm. */
    calm?: boolean;
    onsubmit: (draft: NewProductDraft) => void;
    oncancel?: () => void;
  } = $props();

  const uid = $props.id();
  const d = $derived(meta.value?.new_product_defaults);

  // svelte-ignore state_referenced_locally -- seeded once from the initial values
  let name = $state(initial.name);
  // svelte-ignore state_referenced_locally
  let locationId = $state<number | null>(initial.location_id ?? null);
  // svelte-ignore state_referenced_locally
  let quId = $state<number | null>(initial.qu_id ?? null);
  // svelte-ignore state_referenced_locally
  let groupId = $state<number | null>(initial.product_group_id ?? null);
  // svelte-ignore state_referenced_locally
  let days = $state<number | null>(initial.default_best_before_days && initial.default_best_before_days > 0 ? initial.default_best_before_days : null);

  // Fill defaults once Grocy's presets are known.
  $effect(() => {
    if (!d) return;
    if (locationId == null) locationId = d.location_id;
    if (quId == null) quId = d.qu_id;
    if (groupId == null && initial.product_group_id === undefined) groupId = d.product_group_id;
    if (days == null && initial.default_best_before_days === undefined && d.default_best_before_days > 0)
      days = d.default_best_before_days;
  });

  function submit(e: SubmitEvent) {
    e.preventDefault();
    if (!name.trim() || locationId == null || quId == null) return;
    const n = Math.round(Number(days ?? 0));
    onsubmit({
      name: name.trim(),
      location_id: locationId,
      qu_id: quId,
      product_group_id: groupId,
      default_best_before_days: Number.isFinite(n) && n > 0 ? n : 0,
    });
  }
</script>

<form class="np" onsubmit={submit}>
  <label class="field">
    <span>Product name</span>
    <input bind:value={name} required maxlength="200" placeholder="What is it called in your kitchen?" />
  </label>
  {#if !meta.value}
    <p class="small muted">{meta.error ?? 'Loading locations and units from Grocy…'}</p>
  {:else}
    <div class="two">
      <label class="field">
        <span>Kept in</span>
        <select bind:value={locationId} required>
          {#each meta.value.locations as l (l.id)}<option value={l.id}>{l.name}</option>{/each}
        </select>
      </label>
      <label class="field">
        <span>Counted in</span>
        <select bind:value={quId} required>
          {#each meta.value.quantity_units as u (u.id)}<option value={u.id}>{u.name}</option>{/each}
        </select>
      </label>
    </div>
    <div class="two">
      <label class="field" for="{uid}-days">
        <span>Usually keeps for</span>
        <span class="days">
          <input id="{uid}-days" bind:value={days} type="number" inputmode="numeric" min="0" max="3650" placeholder="Doesn't expire" />
          <span class="unit">days</span>
        </span>
      </label>
      {#if meta.value.product_groups.length}
        <label class="field">
          <span>Group <span class="opt">(optional)</span></span>
          <select bind:value={groupId}>
            <option value={null}>None</option>
            {#each meta.value.product_groups as g (g.id)}<option value={g.id}>{g.name}</option>{/each}
          </select>
        </label>
      {/if}
    </div>
  {/if}
  {#if error && calm}
    <p class="note" role="status">{error}</p>
  {:else if error}
    <p class="form-error" role="alert">{error}</p>
  {/if}
  <div class="actions">
    {#if oncancel}<button type="button" class="btn" onclick={oncancel}>Cancel</button>{/if}
    <button class="btn primary grow" disabled={busy || !name.trim() || locationId == null || quId == null}>
      {#if busy}<span class="spinner"></span>{/if}
      {submitLabel}
    </button>
  </div>
  <p class="small muted">The product is created in Grocy when you add the trip.</p>
</form>

<style>
  .np {
    display: grid;
    gap: 14px;
  }
  .two {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
  }
  .days {
    position: relative;
    display: block;
  }
  .days input {
    padding-right: 3.5em;
  }
  .unit {
    position: absolute;
    right: 14px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--ink-3);
    pointer-events: none;
  }
  .opt {
    font-weight: 400;
  }
  .actions {
    display: flex;
    gap: 10px;
  }
  .grow {
    flex: 1;
  }
</style>
