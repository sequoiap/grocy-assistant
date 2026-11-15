<script lang="ts">
  import { session } from '../lib/session.svelte';
  import AuthFrame from '../components/AuthFrame.svelte';

  let { message }: { message: string } = $props();
</script>

<AuthFrame title="Can't reach Grocy Assistant">
  <p class="muted">{message}</p>
  <button type="button" class="btn primary big block" onclick={() => session.boot()}>Try again</button>
</AuthFrame>
