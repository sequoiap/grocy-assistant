<script lang="ts">
  // Which Grocy this server talks to (fixed by its configuration), and a way
  // for the person to check that their own connection to it works.
  import { api, errorMessage } from '../lib/api';
  import type { TestResult } from '../lib/types';
  import Icon from '../components/Icon.svelte';

  let { grocyUrl }: { grocyUrl: string | null } = $props();

  let testing = $state(false);
  let result = $state<TestResult | null>(null);

  async function test() {
    testing = true;
    result = null;
    try {
      result = await api.testGrocy();
    } catch (err) {
      result = { ok: false, message: errorMessage(err) };
    } finally {
      testing = false;
    }
  }
</script>

<div class="conn">
  <div class="status">
    <Icon name="link" />
    <div>
      <p class="label">Grocy address</p>
      <p class="url">{grocyUrl ?? '…'}</p>
      <p class="small muted">Set on the server, so it can't be changed here. What you add shows up under your name in Grocy.</p>
    </div>
  </div>
  <div class="row">
    <button type="button" class="btn" onclick={test} disabled={testing}>
      {#if testing}<span class="spinner"></span>{:else}<Icon name="refresh" size={20} />{/if} Test my connection
    </button>
  </div>
  {#if result}
    <p class="note {result.ok ? 'good' : 'bad'}" role="status">
      <Icon name={result.ok ? 'check' : 'alert'} size={18} />
      <span>{result.message}</span>
    </p>
  {/if}
</div>

<style>
  .conn {
    display: grid;
    gap: 12px;
  }
  .status {
    display: flex;
    gap: 12px;
    align-items: flex-start;
  }
  .status :global(svg) {
    color: var(--cobalt);
    margin-top: 2px;
    flex: none;
  }
  .status > div {
    display: grid;
    gap: 2px;
    min-width: 0;
  }
  .label {
    font-weight: 650;
    font-size: var(--fs-sm);
    color: var(--ink-2);
  }
  .url {
    font-weight: 700;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
</style>
