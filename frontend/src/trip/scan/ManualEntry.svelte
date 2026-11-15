<script lang="ts">
  // Typed barcodes, and keyboard-wedge scanners (USB/Bluetooth) that "type" digits + Enter.
  import { onMount } from 'svelte';
  import Icon from '../../components/Icon.svelte';
  import { viewport } from '../../lib/ui.svelte';

  let { onsubmit, disabled = false }: { onsubmit: (code: string) => void; disabled?: boolean } = $props();

  let value = $state('');
  let input: HTMLInputElement | undefined = $state();

  function submit(e: SubmitEvent) {
    e.preventDefault();
    const code = value.trim();
    if (!code) return;
    onsubmit(code);
    value = '';
  }

  onMount(() => {
    // On desktops, keep the box ready for a wedge scanner.
    if (!viewport.coarse) input?.focus();

    // Wedge scanners also work when focus is elsewhere on the page: they type far
    // faster than a person, so a quick burst ending in Enter counts as a scan.
    let buffer = '';
    let first = 0;
    let last = 0;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.closest('input, textarea, select, [contenteditable="true"]') || t.closest('dialog'))) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const now = performance.now();
      if (now - last > 80) {
        buffer = '';
        first = now;
      }
      last = now;
      if (e.key === 'Enter') {
        const fast = buffer.length >= 4 && (now - first) / buffer.length < 40;
        if (fast) {
          e.preventDefault();
          onsubmit(buffer);
        }
        buffer = '';
      } else if (e.key.length === 1) {
        buffer += e.key;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });
</script>

<form class="manual" onsubmit={submit}>
  <label class="sr-only" for="manual-code">Barcode</label>
  <span class="lead" aria-hidden="true"><Icon name="keyboard" /></span>
  <input
    bind:this={input}
    bind:value
    id="manual-code"
    inputmode="numeric"
    autocomplete="off"
    autocapitalize="none"
    spellcheck="false"
    enterkeyhint="go"
    placeholder="Type a barcode"
    {disabled}
  />
  <button class="btn primary" disabled={disabled || !value.trim()}>Add</button>
</form>

<style>
  .manual {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 6px 6px 14px;
    border: 2px solid var(--line);
    border-radius: 18px;
    background: var(--surface);
  }
  .manual:focus-within {
    border-color: var(--cobalt);
  }
  .lead {
    color: var(--ink-3);
    display: grid;
  }
  .manual .btn {
    flex: none;
    white-space: nowrap;
    min-width: 76px;
  }
  input {
    border: 0 !important;
    box-shadow: none !important;
    padding-inline: 4px !important;
    background: transparent !important;
    min-width: 0;
    letter-spacing: 0.04em;
  }
</style>
