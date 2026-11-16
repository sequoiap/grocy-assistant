<script lang="ts">
  // The one signed-out screen. People sign in with their Grocy account; the app
  // has no accounts of its own. An API key is the way in when a password can't be used.
  //
  // Behind a single-sign-on proxy nobody should get here: the proxy signs people
  // in. If they do, it didn't, and there is no password to ask for (that Grocy has
  // no login form), so the screen offers another go and the API key.
  import { api, errorMessage, isApiKeyRequired } from '../lib/api';
  import { session } from '../lib/session.svelte';
  import AuthFrame from '../components/AuthFrame.svelte';
  import Icon from '../components/Icon.svelte';
  import KeyHelp from '../components/KeyHelp.svelte';

  let username = $state('');
  let password = $state('');
  let apiKey = $state('');
  let useKey = $state(false);
  /** The server's explanation when it asked for a key after a correct username and password. */
  let keyReason = $state<string | null>(null);
  let error = $state<string | null>(null);
  let busy = $state(false);
  const sso = $derived(session.status?.single_sign_on ?? false);

  function switchWay() {
    useKey = !useKey;
    keyReason = null;
    error = null;
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    error = null;
    session.setNotice(null);
    busy = true;
    try {
      const body = useKey ? { api_key: apiKey.trim() } : { username: username.trim(), password };
      session.signedIn(await api.login(body));
    } catch (err) {
      if (isApiKeyRequired(err)) {
        useKey = true;
        keyReason = errorMessage(err);
      } else {
        error = errorMessage(err);
      }
    } finally {
      busy = false;
    }
  }
</script>

{#snippet notice()}
  {#if session.notice}
    <div class="note warn" role="alert"><Icon name="alert" size={18} /><p>{session.notice}</p></div>
  {/if}
{/snippet}

{#if sso && !useKey}
  <AuthFrame title="Sign in" lede="You are normally signed in here automatically. That didn't happen this time.">
    {@render notice()}
    <button type="button" class="btn primary big block" onclick={() => session.goThroughProxy()}>Try again</button>
    <p class="alt">
      <button type="button" class="linklike" onclick={switchWay}>Use a Grocy API key instead</button>
    </p>
  </AuthFrame>
{:else}
  <AuthFrame
    title="Sign in"
    lede={sso
      ? 'A Grocy API key signs you in on this device.'
      : "Use your Grocy account. It's the same username and password you sign in to Grocy with."}
  >
    {@render notice()}
    <form onsubmit={submit} class="form">
      {#if error}<p class="form-error" role="alert">{error}</p>{/if}
      {#if useKey}
        {#if keyReason}
          <div class="note" role="status"><Icon name="info" size={18} /><p>{keyReason}</p></div>
        {/if}
        <KeyHelp />
        <label class="field">
          <span>Your Grocy API key</span>
          <input bind:value={apiKey} name="grocy-api-key" autocomplete="off" autocapitalize="none" autocorrect="off" spellcheck="false" required />
        </label>
      {:else}
        <label class="field">
          <span>Grocy username</span>
          <input bind:value={username} name="username" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" required />
        </label>
        <label class="field">
          <span>Grocy password</span>
          <input bind:value={password} type="password" name="password" autocomplete="current-password" required />
          <small class="hint">Only used to sign you in to Grocy. It isn't kept here.</small>
        </label>
      {/if}
      <button class="btn primary big block" disabled={busy}>
        {#if busy}<span class="spinner"></span> Checking with Grocy…{:else}Sign in{/if}
      </button>
    </form>
    <p class="alt">
      <button type="button" class="linklike" onclick={switchWay}>
        {#if sso}Back{:else if useKey}Use your Grocy username and password instead{:else}Use a Grocy API key instead{/if}
      </button>
    </p>
  </AuthFrame>
{/if}

<style>
  .form {
    display: grid;
    gap: 16px;
  }
  .alt {
    text-align: center;
  }
</style>
