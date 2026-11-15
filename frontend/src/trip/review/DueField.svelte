<script lang="ts">
  import { addDaysISO, dueLabel } from '../../lib/format';

  let {
    value,
    source,
    onchange,
  }: {
    value: string; // ISO or "never"
    source: 'manual' | 'default';
    /** null = back to the product's default */
    onchange: (v: string | null) => void;
  } = $props();

  const uid = $props.id();
  const never = $derived(value === 'never');
</script>

<fieldset class="due">
  <legend>Best before</legend>
  <div class="row">
    <input
      id="{uid}-date"
      type="date"
      aria-label="Best before date"
      value={never ? '' : value}
      onchange={(e) => {
        const v = e.currentTarget.value;
        if (v) onchange(v);
      }}
    />
    <button type="button" class="chip" aria-pressed={never} class:on={never} onclick={() => onchange(never ? addDaysISO(7) : 'never')}>
      Doesn't expire
    </button>
  </div>
  <p class="small muted">
    {dueLabel(value)}{source === 'default' ? ", from the product's usual shelf life" : ''}.
    {#if source === 'manual'}
      <button type="button" class="linklike" onclick={() => onchange(null)}>Use the product's default</button>
    {/if}
  </p>
</fieldset>

<style>
  fieldset {
    border: 0;
    padding: 0;
    margin: 0;
    display: grid;
    gap: 6px;
    min-width: 0;
  }
  legend {
    padding: 0;
    margin-bottom: 6px;
    font-weight: 650;
    font-size: var(--fs-sm);
    color: var(--ink-2);
  }
  .row {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .row input {
    flex: 1;
    min-width: 0;
  }
  .chip {
    flex: none;
    min-height: var(--tap);
  }
  .chip.on {
    background: var(--cobalt);
    border-color: var(--cobalt);
    color: var(--on-cobalt);
  }
</style>
