<script lang="ts" module>
  export type DeviceTab = 'show' | 'scan';
  const TAB_KEY = 'ga.devicesTab';

  function readTab(): DeviceTab {
    try {
      return localStorage.getItem(TAB_KEY) === 'scan' ? 'scan' : 'show';
    } catch {
      return 'show';
    }
  }
</script>

<script lang="ts">
  // Working with another device, either way round: show a code that opens the app
  // on a phone or tablet, or scan the code another screen shows to join its trip.
  // Both are offered everywhere: whether this is the phone or the computer can't be
  // told reliably (touchscreen laptops, tablets), and the last choice is remembered.
  import Icon from '../Icon.svelte';
  import Sheet from '../Sheet.svelte';
  import ScanCode from './ScanCode.svelte';
  import ShowCode from './ShowCode.svelte';

  let { open = $bindable(false) }: { open?: boolean } = $props();

  let tab = $state<DeviceTab>(readTab());

  function choose(next: DeviceTab) {
    tab = next;
    try {
      localStorage.setItem(TAB_KEY, next);
    } catch {
      /* not remembered */
    }
  }
</script>

<Sheet bind:open title="Other devices">
  <div class="devices">
    <div class="tabs" role="tablist" aria-label="Other devices">
      <button type="button" role="tab" aria-selected={tab === 'show'} class:on={tab === 'show'} onclick={() => choose('show')}>
        <Icon name="phone" size={20} /> Get the app
      </button>
      <button type="button" role="tab" aria-selected={tab === 'scan'} class:on={tab === 'scan'} onclick={() => choose('scan')}>
        <Icon name="qr" size={20} /> Join a trip
      </button>
    </div>
    <div role="tabpanel">
      {#if tab === 'show'}
        <ShowCode />
      {:else}
        <ScanCode ondone={() => (open = false)} />
      {/if}
    </div>
  </div>
</Sheet>

<style>
  .devices {
    display: grid;
    gap: 16px;
  }
  .tabs {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
    padding: 5px;
    border-radius: var(--r-md);
    background: var(--surface-2);
  }
  .tabs button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-height: 44px;
    padding: 4px 8px;
    border: 0;
    border-radius: var(--r-sm);
    background: transparent;
    color: var(--ink-2);
    font: inherit;
    font-size: var(--fs-sm);
    font-weight: 700;
    cursor: pointer;
  }
  .tabs button.on {
    background: var(--surface);
    color: var(--cobalt);
    box-shadow: var(--shadow);
  }
</style>
