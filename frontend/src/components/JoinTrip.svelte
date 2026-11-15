<script lang="ts">
  // Join a trip that is open on another screen by scanning the QR code it shows.
  // Lives inside the app so it also works from the installed (home-screen) app,
  // where a link opened by the phone's own camera would land in the browser instead.
  import Icon from './Icon.svelte';
  import Sheet from './Sheet.svelte';
  import Viewfinder from '../trip/scan/Viewfinder.svelte';
  import { buzz } from '../lib/feedback';
  import { navigate } from '../lib/router.svelte';
  import { tripIdFromLink } from '../lib/triplink';

  let { open = $bindable(false) }: { open?: boolean } = $props();

  let wrongCode = $state(false);
  let done = false;

  $effect(() => {
    if (open) {
      wrongCode = false;
      done = false;
    }
  });

  function detected(code: string) {
    if (done) return;
    const id = tripIdFromLink(code);
    if (id === null) {
      wrongCode = true;
      return;
    }
    done = true;
    buzz(35);
    open = false;
    navigate(`/trips/${id}/scan`);
  }
</script>

<Sheet bind:open title="Join a trip">
  <div class="join">
    <p>
      On the other screen, open the trip and choose <strong>Use phone as scanner</strong>. Then point this camera at the
      code it shows.
    </p>
    <Viewfinder ondetect={detected} target="qr" hint="Point the camera at the QR code on the other screen." />
    {#if wrongCode}
      <div class="note warn" role="status">
        <Icon name="alert" size={18} />
        <p>That isn't a Grocy Assistant trip code. Product barcodes are scanned inside a trip.</p>
      </div>
    {/if}
  </div>
</Sheet>

<style>
  .join {
    display: grid;
    gap: 14px;
  }
</style>
