<script lang="ts">
  import Icon from './Icon.svelte';
</script>

<div class="offline" role="alert">
  <Icon name="offline" size={20} />
  <p>You're offline. Scans and changes can't be saved until the connection is back.</p>
</div>

<style>
  .offline {
    position: sticky;
    top: 0;
    z-index: 40;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: calc(var(--safe-t) + 10px) var(--gutter) 10px;
    background: var(--saffron);
    color: var(--on-saffron);
    font-weight: 650;
    font-size: var(--fs-sm);
  }
</style>
