<script lang="ts">
  // A way for the person to check that their own connection to Grocy works. The
  // Grocy address itself is server configuration and isn't shown.
  import { api, errorMessage } from '../lib/api';
  import type { TestResult } from '../lib/types';
  import Icon from '../components/Icon.svelte';

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
    <p class="small muted">What you add shows up under your name in Grocy.</p>
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
  .row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
</style>
