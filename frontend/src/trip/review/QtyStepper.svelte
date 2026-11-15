<script lang="ts">
  // − n + with a short delay before saving, so several taps become one change.
  import { onDestroy } from 'svelte';
  import Icon from '../../components/Icon.svelte';
  import { qty } from '../../lib/format';

  let {
    value,
    label,
    disabled = false,
    onchange,
  }: { value: number; label: string; disabled?: boolean; onchange: (v: number) => void } = $props();

  let local = $state<number | null>(null);
  let timer: ReturnType<typeof setTimeout> | undefined;
  const shown = $derived(local ?? value);
  // Whole packs step by one; weighed amounts (1.32 lb) are edited in the details.
  const whole = $derived(Number.isInteger(shown));

  function bump(delta: number) {
    const next = Math.max(1, Math.round(shown + delta));
    if (next === shown) return;
    local = next;
    clearTimeout(timer);
    timer = setTimeout(() => {
      const v = local;
      local = null;
      if (v != null && v !== value) onchange(v);
    }, 600);
  }

  onDestroy(() => {
    clearTimeout(timer);
    if (local != null && local !== value) onchange(local);
  });
</script>

<div class="stepper" role="group" aria-label={label}>
  <button type="button" aria-label="One fewer" disabled={disabled || !whole || shown <= 1} onclick={() => bump(-1)}>
    <Icon name="minus" size={20} />
  </button>
  <output aria-live="polite">{qty(shown)}</output>
  <button type="button" aria-label="One more" disabled={disabled || !whole} onclick={() => bump(1)}>
    <Icon name="plus" size={20} />
  </button>
</div>

<style>
  .stepper {
    display: inline-flex;
    align-items: center;
    border-radius: var(--r-md);
    background: var(--surface-2);
    box-shadow: inset 0 -3px 0 rgba(18, 28, 58, 0.08);
  }
  button {
    display: grid;
    place-items: center;
    width: 46px;
    height: 46px;
    border: 0;
    background: transparent;
    color: var(--cobalt);
    border-radius: var(--r-md);
    cursor: pointer;
    touch-action: manipulation;
  }
  button:active:not(:disabled) {
    background: var(--cobalt-soft);
  }
  button:disabled {
    color: var(--ink-3);
    opacity: 0.45;
    cursor: default;
  }
  output {
    min-width: 2.4ch;
    text-align: center;
    font-size: var(--fs-lg);
    font-weight: 760;
  }
</style>
