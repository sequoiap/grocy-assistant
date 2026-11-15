<script lang="ts">
  // Modal panel: a bottom sheet on phones, a centred dialog on wide screens.
  // Built on <dialog> so focus trapping and Escape come from the browser.
  import type { Snippet } from 'svelte';
  import Icon from './Icon.svelte';

  let {
    open = $bindable(false),
    title,
    children,
    footer,
    wide = false,
    onclose,
  }: {
    open?: boolean;
    title: string;
    children: Snippet;
    footer?: Snippet;
    wide?: boolean;
    onclose?: () => void;
  } = $props();

  const uid = $props.id();
  let dialog: HTMLDialogElement | undefined = $state();

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  });

  function handleClose() {
    open = false;
    onclose?.();
  }

  function onBackdrop(e: MouseEvent) {
    if (e.target === dialog) handleClose();
  }
</script>

<dialog bind:this={dialog} class:wide onclose={handleClose} onclick={onBackdrop} aria-labelledby="{uid}-title">
  {#if open}
    <div class="panel">
      <header>
        <h2 id="{uid}-title">{title}</h2>
        <button type="button" class="btn ghost icon" onclick={handleClose} aria-label="Close">
          <Icon name="x" />
        </button>
      </header>
      <div class="body">
        {@render children()}
      </div>
      {#if footer}
        <footer>{@render footer()}</footer>
      {/if}
    </div>
  {/if}
</dialog>

<style>
  dialog {
    padding: 0;
    border: 0;
    margin: auto auto 0;
    width: 100%;
    max-width: 100%;
    /* Heights here are in viewport units only. A percentage on .panel would refer
       to this dialog's own content height, which Safari resolves to zero: the
       sheet then collapses to its top border at the bottom of the screen. */
    max-height: 92dvh;
    background: transparent;
    color: var(--ink);
    overflow: visible;
  }
  dialog::backdrop {
    background: rgba(8, 12, 30, 0.55);
  }
  .panel {
    display: flex;
    flex-direction: column;
    max-height: 92dvh;
    background: var(--surface);
    border-radius: var(--r-lg) var(--r-lg) 0 0;
    border-top: 4px solid var(--cobalt);
    box-shadow: var(--shadow);
    padding-bottom: var(--safe-b);
    animation: rise 180ms ease-out;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 14px 8px 6px var(--gutter);
  }
  h2 {
    font-size: var(--fs-lg);
  }
  .body {
    padding: 8px var(--gutter) 20px;
    overflow-y: auto;
    overscroll-behavior: contain;
  }
  footer {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    justify-content: flex-end;
    padding: 12px var(--gutter) 16px;
    border-top: 1px solid var(--line);
  }
  @media (min-width: 720px) {
    dialog {
      margin: auto;
      width: min(560px, calc(100% - 48px));
    }
    dialog.wide {
      width: min(860px, calc(100% - 48px));
    }
    .panel {
      border-radius: var(--r-lg);
      max-height: 86dvh;
    }
  }
  @keyframes rise {
    from {
      transform: translateY(24px);
      opacity: 0;
    }
  }
</style>
