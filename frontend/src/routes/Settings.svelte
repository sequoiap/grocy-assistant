<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage } from '../lib/api';
  import { back } from '../lib/router.svelte';
  import { meta, session } from '../lib/session.svelte';
  import type { SettingsOut } from '../lib/types';
  import Icon from '../components/Icon.svelte';
  import TopBar from '../components/TopBar.svelte';
  import GrocyConnection from '../settings/GrocyConnection.svelte';
  import AISettings from '../settings/AISettings.svelte';

  let settings = $state<SettingsOut | null>(null);
  let settingsError = $state<string | null>(null);
  const user = $derived(session.user);
  // The person has picked a provider of their own (which normally means it is the one in use).
  const ownSet = $derived(settings ? settings.personal_ai.provider !== 'none' : false);

  async function load() {
    settingsError = null;
    try {
      settings = await api.settings();
    } catch (err) {
      settingsError = errorMessage(err);
    }
  }

  onMount(() => {
    void meta.load();
    void load();
  });
</script>

<TopBar>
  {#snippet start()}
    <button type="button" class="btn ghost icon" aria-label="Back" onclick={() => back('/')}><Icon name="back" /></button>
  {/snippet}
  {#snippet title()}
    <h1 class="title">Settings</h1>
  {/snippet}
</TopBar>

<main class="page settings">
  <section class="sec" aria-labelledby="s-you">
    <h2 id="s-you">You</h2>
    <p class="who">
      <Icon name="user" />
      <span>
        Signed in as <strong>{user?.display_name || user?.username}</strong
        >{#if user && user.display_name && user.display_name !== user.username}&nbsp;({user.username}){/if}{#if user?.is_admin}, a Grocy admin{/if}
      </span>
    </p>
    <GrocyConnection grocyUrl={settings?.grocy_url ?? null} />
  </section>

  {#if settingsError}
    <div class="note bad"><Icon name="alert" size={18} /><p>{settingsError} <button class="linklike" onclick={load}>Try again</button></p></div>
  {:else if settings}
    <section class="sec" aria-labelledby="s-ai">
      <h2 id="s-ai">AI help with receipts</h2>
      <p class="muted small">
        An AI model can read receipts that the built-in text recognition struggles with, and help match lines to products.
        Receipt photos are sent to whichever provider is in use.
      </p>
      <div class="note in-use" role="status">
        <Icon name={settings.ai_source === 'none' ? 'info' : 'spark'} size={18} />
        <p>
          {#if settings.ai_source === 'personal'}
            <strong>In use for your receipts: your own settings.</strong>
            To go back to the household default, choose “Use the household default” below and save.
          {:else if settings.ai_source === 'instance'}
            <strong>In use for your receipts: the household's AI.</strong>
            {#if ownSet}
              Your own settings below aren't being used. Test them to check they work.
            {:else}
              An admin set it up for everyone, so there's nothing you need to do. To use a different one yourself, choose a provider below.
            {/if}
          {:else}
            <strong>In use for your receipts: no AI.</strong>
            They are read by the built-in text recognition only.
            {#if ownSet}
              Your own settings below aren't being used. Test them to check they work.
            {:else if settings.instance_ai}
              Choose a provider below just for yourself, or set one up for the whole household further down.
            {:else}
              Choose a provider below to use your own, or ask a Grocy admin to set one up for the household.
            {/if}
          {/if}
        </p>
      </div>
      <AISettings scope="personal" ai={settings.personal_ai} onsaved={(s) => (settings = s)} />
    </section>

    {#if settings.instance_ai}
      <section class="sec" aria-labelledby="s-household">
        <h2 id="s-household">Household AI</h2>
        <p class="muted small">
          Only Grocy admins see this part. It is the default for everyone who hasn't set their own, and their receipt photos are sent to the provider you choose here.
        </p>
        <AISettings scope="instance" ai={settings.instance_ai} onsaved={(s) => (settings = s)} />
      </section>
    {/if}
  {:else}
    <div class="sec" aria-busy="true"></div>
  {/if}

  <section class="sec end">
    {#if user?.via_proxy}
      <!-- Signing out here would be undone by the very next request. -->
      <p class="small muted">Your single sign-on signs you in here. To sign out, sign out there.</p>
    {:else}
      <button type="button" class="btn block" onclick={() => session.signOut()}><Icon name="logout" /> Sign out</button>
    {/if}
    <p class="small muted version">
      Grocy Assistant {session.status?.version ?? ''}{#if meta.value?.grocy_version}, {meta.value.grocy_reachable === false ? 'last connected to' : 'connected to'} Grocy {meta.value.grocy_version}{/if}
    </p>
  </section>
</main>

<style>
  .title {
    font-size: var(--fs-lg);
  }
  .settings {
    display: grid;
    gap: 14px;
    padding-top: 16px;
  }
  .sec {
    display: grid;
    gap: 14px;
    padding: 20px;
    border-radius: var(--r-lg);
    background: var(--surface);
  }
  .sec h2 {
    font-size: var(--fs-xl);
  }
  .sec > .muted {
    margin-top: -8px;
  }
  .who {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .who :global(svg) {
    color: var(--cobalt);
  }
  .in-use {
    background: var(--cobalt-soft);
  }
  .in-use :global(svg) {
    color: var(--cobalt);
  }
  .end {
    background: transparent;
    padding-inline: 0;
  }
  .version {
    text-align: center;
  }
  @media (max-width: 520px) {
    .sec {
      padding: 18px 16px;
      margin-inline: calc(var(--gutter) * -1);
      border-radius: 0;
    }
    .end {
      margin-inline: 0;
    }
  }
</style>
