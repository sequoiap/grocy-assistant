<script lang="ts">
  // Shown when a single-sign-on proxy in front of the app has stopped letting this
  // browser through (its own session ran out). The app normally goes there by
  // itself; this is what is on screen meanwhile, and the way there if it didn't.
  import { session } from '../lib/session.svelte';
  import AuthFrame from '../components/AuthFrame.svelte';
</script>

<AuthFrame title="Sign in again" lede="Your sign-in has run out. Sign in again to carry on where you were.">
  <button type="button" class="btn primary big block" onclick={() => session.goThroughProxy()}>Sign in</button>
</AuthFrame>
