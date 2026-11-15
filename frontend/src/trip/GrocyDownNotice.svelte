<script lang="ts">
  // Shown while the server is working from its saved copy of Grocy's data.
  // Not the offline banner: that one is about this device's own connection.
  import Icon from '../components/Icon.svelte';

  let { readOnly = false }: { readOnly?: boolean } = $props();
</script>

<div class="grocy-down" role="status">
  <div class="note">
    <Icon name="info" size={18} />
    <p>
      <strong>Grocy can't be reached right now.</strong>
      {#if readOnly}
        You can still look through this trip. Undo will work once Grocy is back.
      {:else}
        Scanning and editing still work, and this trip is saved. You can add it to Grocy once it's back.
      {/if}
    </p>
  </div>
</div>

<style>
  .grocy-down {
    width: 100%;
    max-width: 1180px;
    margin: 0 auto;
    padding: 12px var(--gutter) 0;
  }
  .note {
    background: var(--cobalt-soft);
  }
  .note :global(svg) {
    color: var(--cobalt);
  }
</style>
