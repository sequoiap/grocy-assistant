<script lang="ts">
  // A QR code of this app's address, and how to put the app on a home screen from
  // there: the quickest way to get the address onto a phone or tablet.
  import { renderSVG } from 'uqr';
  import Icon from '../Icon.svelte';
  import { phoneLinkProblem } from '../../lib/triplink';
  import { toasts } from '../../lib/ui.svelte';

  const link = `${location.origin}/`;
  // Generated locally from our own URL, so it is safe to inline.
  const svg = renderSVG(link, { ecc: 'M', border: 2 });
  const problem = phoneLinkProblem();

  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      toasts.success('Link copied');
    } catch {
      toasts.error("Couldn't copy. Select the link and copy it by hand.");
    }
  }
</script>

<div class="show-code">
  <div class="qr" role="img" aria-label="QR code with the address of Grocy Assistant">
    {@html svg}
  </div>
  {#if problem === 'local'}
    <div class="note warn">
      <Icon name="alert" size={18} />
      <p>
        You opened Grocy Assistant as <strong>{location.host}</strong>, an address that only works on this device. Open
        it here by the https address the other device uses, then show this code again.
      </p>
    </div>
  {:else if problem === 'insecure'}
    <div class="note warn">
      <Icon name="alert" size={18} />
      <p>
        This page isn't on HTTPS. Phones and tablets can open it, but won't allow the camera for scanning or installing it as an
        app. Open Grocy Assistant through its https address first, then show this code again.
      </p>
    </div>
  {/if}
  <ol>
    <li>Point the other device's camera at the code and open the link.</li>
    <li>Sign in. That's only needed once per device.</li>
    <li>
      Add it to the home screen, so it opens like an app:
      <ul>
        <li><strong>iPhone or iPad:</strong> in Safari, tap <em>Share</em>, then <em>Add to Home Screen</em>.</li>
        <li><strong>Android:</strong> in Chrome, tap the <em>⋮</em> menu, then <em>Install app</em> (or <em>Add to Home screen</em>).</li>
      </ul>
    </li>
  </ol>
  <p class="small muted">
    To scan for a trip that's open here, choose <strong>Use phone as scanner</strong> inside the trip instead.
  </p>
  <div class="url">
    <code>{link}</code>
    <button type="button" class="btn small" onclick={copy}><Icon name="link" size={18} /> Copy</button>
  </div>
</div>

<style>
  .show-code {
    display: grid;
    gap: 16px;
  }
  /* Always dark-on-white with a quiet zone, whatever the theme: scanners need the contrast. */
  .qr {
    justify-self: center;
    width: min(240px, 70vw);
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
  ul {
    margin: 6px 0 0;
    padding-left: 1.1em;
    display: grid;
    gap: 4px;
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
    color: var(--ink-2);
  }
  .url .btn {
    flex: none;
  }
</style>
