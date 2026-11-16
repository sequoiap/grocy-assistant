<script lang="ts">
  import { onMount } from 'svelte';
  import { isAccountInvalid, onAccountInvalid, onProxySignIn, onUnauthorized } from './lib/api';
  import { installRouter, match, navigate, router } from './lib/router.svelte';
  import { session } from './lib/session.svelte';
  import { network, viewport } from './lib/ui.svelte';
  import Toasts from './components/Toasts.svelte';
  import OfflineBanner from './components/OfflineBanner.svelte';
  import UpdatePrompt from './components/UpdatePrompt.svelte';
  import Login from './routes/Login.svelte';
  import Home from './routes/Home.svelte';
  import Settings from './routes/Settings.svelte';
  import TripPage from './trip/TripPage.svelte';
  import BootError from './routes/BootError.svelte';
  import ProxySignIn from './routes/ProxySignIn.svelte';
  import NotFound from './routes/NotFound.svelte';

  const route = $derived(match(router.path));

  onMount(() => {
    const cleanups = [installRouter(), network.install(), viewport.install(), session.watch()];
    // An expired session drops to the sign-in screen quietly. When Grocy has
    // rejected the account, the server's reason goes along to be shown there.
    onUnauthorized((err) => session.ended(isAccountInvalid(err) ? err.message : null));
    onAccountInvalid(() => session.signInAgain());
    onProxySignIn(() => session.stoppedByProxy());
    void session.boot();
    return () => cleanups.forEach((c) => c());
  });

  // The only question is whether someone is signed in. Returns a path to redirect to, or null.
  const redirect = $derived.by((): string | null => {
    if (!session.ready || session.bootError || session.proxyWantsSignIn) return null;
    const name = route.name;
    if (!session.user) {
      if (name === 'login') return null;
      // Come back to where they were headed (a phone opening a trip link), but not to a dead end.
      const keep = name !== 'home' && name !== 'notfound';
      return keep ? `/login?next=${encodeURIComponent(router.path)}` : '/login';
    }
    if (name === 'login') {
      const next = new URLSearchParams(router.search).get('next');
      return next && next.startsWith('/') && !next.startsWith('//') ? next : '/';
    }
    return null;
  });

  $effect(() => {
    if (redirect) navigate(redirect, { replace: true });
  });
</script>

{#if !network.online}
  <OfflineBanner />
{/if}

{#if session.proxyWantsSignIn}
  <ProxySignIn />
{:else if !session.ready}
  <div class="splash" aria-busy="true" aria-label="Loading"></div>
{:else if session.bootError}
  <BootError message={session.bootError} />
{:else if !redirect}
  {#if route.name === 'login'}
    <Login />
  {:else if route.name === 'home'}
    <Home />
  {:else if route.name === 'settings'}
    <Settings />
  {:else if route.name === 'trip'}
    {#key route.id}
      <TripPage id={route.id} step={route.step} />
    {/key}
  {:else}
    <NotFound />
  {/if}
{/if}

<Toasts />
<UpdatePrompt />

<style>
  .splash {
    min-height: 100dvh;
  }
</style>
