<script lang="ts">
  // "Use your phone as the scanner": a QR code that opens this same trip on another
  // device. Both devices then show the trip live, so scans and receipt photos taken
  // on the phone appear here within a couple of seconds.
  import { renderSVG } from 'uqr';
  import Icon from '../components/Icon.svelte';
  import Sheet from '../components/Sheet.svelte';
  import { tripLink } from '../lib/triplink';
  import { toasts } from '../lib/ui.svelte';

  let { open = $bindable(false), tripId }: { open?: boolean; tripId: number } = $props();

  const link = $derived(tripLink(tripId));
  // Generated locally from our own URL, so it is safe to inline.
  const svg = $derived(renderSVG(link, { ecc: 'M', border: 2 }));
  // "localhost" means this computer only: a phone following the link would look
  // for the app on itself.
  const localOnly = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
  // Phones refuse camera access on plain http, so the link would open but not scan.
  const insecure = location.protocol !== 'https:';

  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      toasts.success('Link copied');
    } catch {
      toasts.error("Couldn't copy. Select the link and copy it by hand.");
    }
  }
</script>

<Sheet bind:open title="Use your phone as the scanner">
  <div class="link-phone">
    <div class="qr" role="img" aria-label="QR code that opens this trip on another device">
      {@html svg}
    </div>
    <ol>
      <li>Point your phone's camera at the code and open the link. In the installed app, use <strong>Join a trip</strong> on the home screen instead.</li>
      <li>Sign in on the phone if it asks. That's only needed once per phone.</li>
      <li>Scan barcodes and photograph receipts on the phone. They show up on this screen as you go.</li>
    </ol>
    {#if localOnly}
      <div class="note warn">
        <Icon name="alert" size={18} />
        <p>
          You opened Grocy Assistant as <strong>{location.host}</strong>, an address that only works on this computer. Open
          it here by the https address your phone uses, then show this code again.
        </p>
      </div>
    {:else if insecure}
      <div class="note warn">
        <Icon name="alert" size={18} />
        <p>This page isn't on HTTPS, and phones only allow the camera on HTTPS. Open Grocy Assistant through its https address first, then show this code again.</p>
      </div>
    {/if}
    <div class="url">
      <code>{link}</code>
      <button type="button" class="btn small" onclick={copy}><Icon name="link" size={18} /> Copy</button>
    </div>
  </div>
</Sheet>

<style>
  .link-phone {
    display: grid;
    gap: 16px;
  }
  /* Always dark-on-white with a quiet zone, whatever the theme: scanners need the contrast. */
  .qr {
    justify-self: center;
    width: min(260px, 70vw);
    aspect-ratio: 1;
    padding: 10px;
    border-radius: 16px;
    background: #fff;
    border: 1px solid var(--line);
  }
  .qr :global(svg) {
    display: block;
    width: 100%;
    height: 100%;
  }
  ol {
    margin: 0;
    padding-left: 1.3em;
    display: grid;
    gap: 6px;
  }
  .url {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .url code {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
    font-size: 0.85rem;
    color: var(--ink-2, inherit);
  }
  .url .btn {
    flex: none;
  }
</style>
