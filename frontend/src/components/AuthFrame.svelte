<script lang="ts">
  // Frame for the signed-out screens: a cobalt rim with the app mark, then the form.
  import type { Snippet } from 'svelte';
  import Mark from './Mark.svelte';

  let { title, lede, children }: { title: string; lede?: string; children: Snippet } = $props();
</script>

<div class="frame">
  <div class="rim">
    <div class="brand">
      <Mark size={44} />
      <span>Grocy Assistant</span>
    </div>
  </div>
  <main class="panel">
    <h1>{title}</h1>
    {#if lede}<p class="lede">{lede}</p>{/if}
    <div class="content">
      {@render children()}
    </div>
  </main>
</div>

<style>
  .frame {
    min-height: 100dvh;
    display: flex;
    flex-direction: column;
    background: linear-gradient(var(--cobalt) 0 180px, var(--paper) 180px);
  }
  @media (prefers-color-scheme: dark) {
    .frame {
      background: linear-gradient(var(--cobalt-soft) 0 180px, var(--paper) 180px);
    }
  }
  .rim {
    padding: calc(var(--safe-t) + 28px) var(--gutter) 36px;
    color: var(--on-cobalt);
  }
  @media (prefers-color-scheme: dark) {
    .rim {
      color: var(--ink);
    }
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 12px;
    max-width: 480px;
    margin: 0 auto;
    font-size: var(--fs-lg);
    font-weight: 760;
    letter-spacing: -0.01em;
  }
  .panel {
    flex: 1;
    width: 100%;
    max-width: 480px;
    margin: 0 auto;
    padding: 28px var(--gutter) calc(var(--safe-b) + 32px);
    background: var(--surface);
    border-radius: var(--r-lg) var(--r-lg) 0 0;
  }
  @media (min-width: 560px) {
    .panel {
      flex: none;
      padding: 32px 32px 36px;
      border-radius: var(--r-lg);
      box-shadow: var(--shadow);
      margin-bottom: 48px;
    }
  }
  h1 {
    font-size: var(--fs-2xl);
  }
  .lede {
    margin-top: 8px;
    color: var(--ink-2);
    max-width: 38ch;
  }
  .content {
    display: grid;
    gap: 18px;
    margin-top: 24px;
  }
</style>
