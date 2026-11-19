<script lang="ts">
  // Join a trip that is open on another screen by scanning the QR code it shows.
  // Lives inside the app so it also works from the installed (home-screen) app,
  // where a link opened by the phone's own camera would land in the browser instead.
  import Icon from '../Icon.svelte';
  import Viewfinder from '../../trip/scan/Viewfinder.svelte';
  import { buzz } from '../../lib/feedback';
  import { navigate } from '../../lib/router.svelte';
  import { tripIdFromLink } from '../../lib/triplink';

  let { ondone }: { ondone: () => void } = $props();

  let wrongCode = $state(false);
  let done = false;

  function detected(code: string) {
    if (done) return;
    const id = tripIdFromLink(code);
    if (id === null) {
      wrongCode = true;
      return;
    }
    done = true;
    buzz(35);
    ondone();
    navigate(`/trips/${id}/scan`);
  }
</script>

<div class="scan-code">
  <p>
    Join a trip that's open on another screen. There, open the trip and choose <strong>Use phone as scanner</strong>,
    then point this camera at the code it shows.
  </p>
  <Viewfinder ondetect={detected} target="qr" hint="Point the camera at the QR code on the other screen." />
  {#if wrongCode}
    <div class="note warn" role="status">
      <Icon name="alert" size={18} />
      <p>That isn't a Grocy Assistant trip code. Product barcodes are scanned inside a trip.</p>
    </div>
  {/if}
</div>

<style>
  .scan-code {
    display: grid;
    gap: 14px;
  }
</style>
