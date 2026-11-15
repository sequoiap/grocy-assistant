<script lang="ts">
  import type { Snippet } from 'svelte';

  let { start, title, end }: { start?: Snippet; title: Snippet; end?: Snippet } = $props();
</script>

<header class="topbar">
  <div class="inner">
    {#if start}<div class="start">{@render start()}</div>{/if}
    <div class="title">{@render title()}</div>
    {#if end}<div class="end">{@render end()}</div>{/if}
  </div>
</header>

<style>
  .topbar {
    position: sticky;
    top: 0;
    z-index: 20;
    background: color-mix(in srgb, var(--paper) 88%, transparent);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--line);
    padding-top: var(--safe-t);
  }
  .inner {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 60px;
    max-width: var(--topbar-max, 760px);
    margin: 0 auto;
    padding: 0 8px;
  }
  .title {
    flex: 1;
    min-width: 0;
    padding: 0 8px;
  }
  .start,
  .end {
    display: flex;
    align-items: center;
    gap: 4px;
  }
</style>
