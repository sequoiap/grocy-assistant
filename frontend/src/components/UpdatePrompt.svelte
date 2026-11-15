<script lang="ts">
  // "New version available" prompt for the service worker. Nothing reloads by itself.
  import { onMount } from 'svelte';

  let needRefresh = $state(false);
  let update: ((reload?: boolean) => Promise<void>) | null = null;

  onMount(() => {
    if (import.meta.env.DEV || !('serviceWorker' in navigator)) return;
    let interval: ReturnType<typeof setInterval> | undefined;
    let check: (() => void) | undefined;
    // An installed app coming back from the background is resumed, not reloaded,
    // so on a phone "when it is opened" has to mean "when it becomes visible".
    const onVisible = () => {
      if (document.visibilityState === 'visible') check?.();
    };
    document.addEventListener('visibilitychange', onVisible);
    void import('virtual:pwa-register').then(({ registerSW }) => {
      update = registerSW({
        onNeedRefresh() {
          needRefresh = true;
        },
        onRegisteredSW(_url, registration) {
          if (!registration) return;
          check = () => void registration.update().catch(() => {});
          // And every hour while the app stays open.
          interval = setInterval(check, 60 * 60 * 1000);
        },
      });
    });
    return () => {
      clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
    };
  });
</script>

{#if needRefresh}
  <div class="update" role="status">
    <p>A new version is ready.</p>
    <button type="button" class="btn small primary" onclick={() => update?.(true)}>Reload</button>
    <button type="button" class="btn small ghost" onclick={() => (needRefresh = false)}>Later</button>
  </div>
{/if}

<style>
  .update {
    position: fixed;
    top: calc(var(--safe-t) + 10px);
    left: 50%;
    transform: translateX(-50%);
    z-index: 60;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 6px 6px 16px;
    border-radius: 999px;
    background: var(--surface);
    border: 2px solid var(--cobalt);
    box-shadow: var(--shadow);
    font-weight: 650;
    font-size: var(--fs-sm);
    white-space: nowrap;
  }
</style>
