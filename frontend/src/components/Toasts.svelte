<script lang="ts">
  import { toasts } from '../lib/ui.svelte';
  import Icon from './Icon.svelte';
</script>

<div class="toasts" role="status" aria-live="polite">
  {#each toasts.list as t (t.id)}
    <div class="toast {t.kind}">
      {#if t.kind === 'error'}
        <Icon name="alert" size={20} />
      {:else if t.kind === 'success'}
        <Icon name="check" size={20} />
      {/if}
      <p>{t.message}</p>
      {#if t.action}
        <button
          type="button"
          class="btn small"
          onclick={() => {
            t.action?.run();
            toasts.dismiss(t.id);
          }}>{t.action.label}</button
        >
      {/if}
      <button type="button" class="close" aria-label="Dismiss" onclick={() => toasts.dismiss(t.id)}>
        <Icon name="x" size={18} />
      </button>
    </div>
  {/each}
</div>

<style>
  .toasts {
    position: fixed;
    left: 0;
    right: 0;
    bottom: calc(var(--safe-b) + 16px);
    z-index: 50;
    display: grid;
    gap: 8px;
    justify-items: center;
    padding: 0 12px;
    pointer-events: none;
  }
  :global(body:has(.trip-nav)) .toasts {
    bottom: calc(var(--safe-b) + var(--nav-h) + 84px);
  }
  @media (min-width: 960px) {
    :global(body:has(.trip-nav)) .toasts {
      bottom: 24px;
    }
  }
  .toast {
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: 10px;
    width: min(520px, 100%);
    padding: 10px 6px 10px 16px;
    border-radius: var(--r-md);
    background: var(--ink);
    color: var(--paper);
    box-shadow: var(--shadow);
    font-weight: 600;
    animation: pop 160ms ease-out;
  }
  .toast.error {
    background: var(--tomato);
    color: #fff;
  }
  @media (prefers-color-scheme: dark) {
    .toast.error {
      color: #2b0b07;
    }
  }
  .toast p {
    flex: 1;
  }
  .toast .btn {
    --btn-bg: rgba(255, 255, 255, 0.16);
    --btn-fg: inherit;
    --btn-lip: none;
  }
  .close {
    display: grid;
    place-items: center;
    width: 40px;
    height: 40px;
    border: 0;
    background: transparent;
    color: inherit;
    opacity: 0.8;
    cursor: pointer;
    border-radius: 10px;
  }
  @keyframes pop {
    from {
      transform: translateY(8px);
      opacity: 0;
    }
  }
</style>
