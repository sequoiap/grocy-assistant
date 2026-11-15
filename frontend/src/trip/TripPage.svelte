<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { api, errorMessage } from '../lib/api';
  import { back, navigate, type TripStep } from '../lib/router.svelte';
  import { meta } from '../lib/session.svelte';
  import { tripTitle, dateTime } from '../lib/format';
  import { toasts } from '../lib/ui.svelte';
  import Icon from '../components/Icon.svelte';
  import TopBar from '../components/TopBar.svelte';
  import Sheet from '../components/Sheet.svelte';
  import StepNav from './StepNav.svelte';
  import ScanStep from './scan/ScanStep.svelte';
  import ReceiptsStep from './receipts/ReceiptsStep.svelte';
  import ReviewStep from './review/ReviewStep.svelte';
  import LinkPhone from './LinkPhone.svelte';
  import GrocyDownNotice from './GrocyDownNotice.svelte';
  import { TripStore } from './trip.svelte';

  let { id, step }: { id: number; step: TripStep } = $props();

  // svelte-ignore state_referenced_locally -- the page is keyed by id
  const store = new TripStore(id);
  let optionsOpen = $state(false);
  let newName = $state('');
  let confirmDelete = $state(false);

  onMount(() => {
    void store.load();
    void meta.load();
  });
  onDestroy(() => store.destroy());

  // Pick a sensible step when the URL doesn't name one.
  $effect(() => {
    const trip = store.trip;
    if (step || !trip) return;
    const target = trip.status === 'submitted' || trip.items.length > 0 ? 'review' : 'scan';
    navigate(`/trips/${id}/${target}`, { replace: true });
  });

  // Matching can change while you were on another step; refresh on every switch.
  let lastStep: TripStep = null;
  $effect(() => {
    if (step && lastStep && step !== lastStep) void store.load();
    lastStep = step;
  });

  function openOptions() {
    newName = store.trip?.name ?? '';
    confirmDelete = false;
    optionsOpen = true;
  }

  async function rename(e: SubmitEvent) {
    e.preventDefault();
    const ok = await store.run(() => api.renameTrip(id, newName.trim()));
    if (ok) optionsOpen = false;
  }

  async function remove() {
    try {
      await api.deleteTrip(id);
      optionsOpen = false;
      toasts.success('Trip deleted');
      navigate('/', { replace: true });
    } catch (err) {
      toasts.error(errorMessage(err));
    }
  }
</script>

<div class="trip-page" style="--topbar-max: 1180px">
  <TopBar>
    {#snippet start()}
      <button type="button" class="btn ghost icon" aria-label="Back to trips" onclick={() => back('/')}>
        <Icon name="back" />
      </button>
    {/snippet}
    {#snippet title()}
      {#if store.trip}
        <p class="t-name">{tripTitle(store.trip)}</p>
        <p class="t-sub small muted">
          {#if store.trip.status === 'submitted' && store.trip.submitted_at}
            Added to Grocy {dateTime(store.trip.submitted_at)}
          {:else}
            Started by {store.trip.created_by}
          {/if}
        </p>
      {/if}
    {/snippet}
    {#snippet end()}
      {#if store.trip && !store.readOnly}
        <button type="button" class="btn ghost small link-btn" onclick={() => (store.linkOpen = true)}>
          <Icon name="phone" size={20} /> <span>Use phone as scanner</span>
        </button>
      {/if}
      {#if store.trip}
        <button type="button" class="btn ghost icon" aria-label="Trip options" onclick={openOptions}>
          <Icon name="more" />
        </button>
      {/if}
    {/snippet}
  </TopBar>

  {#if store.notFound}
    <main class="page">
      <h1>Trip not found</h1>
      <p class="muted">It may have been deleted by someone else in the household.</p>
      <p><a class="btn primary" href="/">Back to trips</a></p>
    </main>
  {:else if store.loadError}
    <main class="page">
      <div class="note bad">
        <Icon name="alert" size={18} />
        <p>{store.loadError} <button class="linklike" onclick={() => store.load()}>Try again</button></p>
      </div>
    </main>
  {:else if !store.trip}
    <main class="page" aria-busy="true"></main>
  {:else}
    <StepNav {store} {step} />
    {#if store.grocyDown}
      <GrocyDownNotice readOnly={store.readOnly} />
    {/if}
    <main class="trip-main" class:review={step === 'review'}>
      {#if step === 'scan'}
        <ScanStep {store} />
      {:else if step === 'receipts'}
        <ReceiptsStep {store} />
      {:else if step === 'review'}
        <ReviewStep {store} />
      {/if}
    </main>
  {/if}
</div>

<LinkPhone bind:open={store.linkOpen} tripId={id} />

<Sheet bind:open={optionsOpen} title="Trip options">
  <form class="rename" onsubmit={rename}>
    <label class="field">
      <span>Name</span>
      <input bind:value={newName} maxlength="120" placeholder={store.trip ? tripTitle({ ...store.trip, name: '' }) : ''} />
    </label>
    <button class="btn primary">Save name</button>
  </form>
  <hr />
  {#if !store.readOnly}
    <button
      type="button"
      class="btn block"
      onclick={() => {
        optionsOpen = false;
        store.linkOpen = true;
      }}
    >
      <Icon name="qr" /> Continue on another device
    </button>
    <hr />
  {/if}
  {#if !confirmDelete}
    <button type="button" class="btn danger block" onclick={() => (confirmDelete = true)}>
      <Icon name="trash" /> Delete this trip
    </button>
  {:else}
    <div class="note warn">
      <Icon name="alert" size={18} />
      <p>
        This deletes the trip and its receipt photos here.
        {#if store.counts.committed > 0}Anything already added stays in Grocy; use Undo first if you want it removed there too.{/if}
      </p>
    </div>
    <div class="row">
      <button type="button" class="btn" onclick={() => (confirmDelete = false)}>Keep it</button>
      <button type="button" class="btn danger" onclick={remove}><Icon name="trash" /> Delete trip</button>
    </div>
  {/if}
</Sheet>

<style>
  /* On phones the top bar is tight; the same action is in the trip options there. */
  .link-btn {
    display: none;
    white-space: nowrap;
  }
  @media (min-width: 720px) {
    .link-btn {
      display: inline-flex;
    }
  }
  .t-name {
    font-weight: 750;
    line-height: 1.2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .t-sub {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .trip-main {
    width: 100%;
    max-width: 1180px;
    margin: 0 auto;
    padding-bottom: calc(var(--safe-b) + var(--nav-h) + 24px);
  }
  .trip-main.review {
    padding-bottom: calc(var(--safe-b) + var(--nav-h) + 110px);
  }
  @media (min-width: 960px) {
    .trip-main,
    .trip-main.review {
      padding-bottom: 48px;
    }
  }
  .rename {
    display: grid;
    gap: 12px;
  }
  hr {
    border: 0;
    border-top: 1px solid var(--line);
    margin: 22px 0;
  }
  .row {
    display: flex;
    gap: 10px;
    margin-top: 12px;
    flex-wrap: wrap;
  }
  .row .btn {
    flex: 1;
  }
</style>
