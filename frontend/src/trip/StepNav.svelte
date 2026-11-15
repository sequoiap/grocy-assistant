<script lang="ts">
  // The three steps of a trip. Bottom bar on phones (thumb reach), top strip on wide screens.
  import { navigate, type TripStep } from '../lib/router.svelte';
  import Icon, { type IconName } from '../components/Icon.svelte';
  import type { TripStore } from './trip.svelte';

  let { store, step }: { store: TripStore; step: TripStep } = $props();

  const steps = $derived.by(() => {
    const trip = store.trip;
    const c = store.counts;
    return [
      { key: 'scan', n: 1, label: 'Scan', icon: 'barcode' as IconName, badge: c.scanned || null, attention: false, busy: false },
      {
        key: 'receipts',
        n: 2,
        label: 'Receipts',
        icon: 'receipt' as IconName,
        badge: trip?.receipts.length || null,
        attention: trip?.receipts.some((r) => r.status === 'failed') ?? false,
        busy: trip?.processing ?? false,
      },
      {
        key: 'review',
        n: 3,
        label: 'Review',
        icon: 'review' as IconName,
        badge: c.attention + c.failed || c.toAdd || null,
        attention: c.attention + c.failed > 0,
        busy: false,
      },
    ];
  });
</script>

<nav class="trip-nav" aria-label="Trip steps">
  <ol>
    {#each steps as s (s.key)}
      <li>
        <a
          href={`/trips/${store.id}/${s.key}`}
          aria-current={step === s.key ? 'page' : undefined}
          onclick={(e) => {
            // Switching steps replaces history so Back still leaves the trip.
            e.preventDefault();
            navigate(`/trips/${store.id}/${s.key}`, { replace: true });
          }}
        >
          <span class="ico"><Icon name={s.icon} size={24} /></span>
          <span class="lbl"><span class="n">{s.n}</span> {s.label}</span>
          {#if s.busy}
            <span class="badge busy" aria-label="reading"><span class="spinner"></span></span>
          {:else if s.badge}
            <span class="badge" class:attention={s.attention}>{s.badge}<span class="sr-only">{s.attention ? ' need attention' : ''}</span></span>
          {/if}
        </a>
      </li>
    {/each}
  </ol>
</nav>

<style>
  .trip-nav {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 30;
    background: var(--surface);
    border-top: 1px solid var(--line);
    padding-bottom: var(--safe-b);
  }
  ol {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    margin: 0 auto;
    padding: 0;
    list-style: none;
    max-width: 640px;
  }
  a {
    position: relative;
    display: grid;
    justify-items: center;
    align-content: center;
    gap: 2px;
    height: var(--nav-h);
    color: var(--ink-2);
    text-decoration: none;
    font-size: var(--fs-sm);
    font-weight: 650;
  }
  a[aria-current='page'] {
    color: var(--cobalt);
  }
  a[aria-current='page']::before {
    content: '';
    position: absolute;
    top: 0;
    left: 22%;
    right: 22%;
    height: 4px;
    border-radius: 0 0 4px 4px;
    background: var(--cobalt);
  }
  .ico {
    display: grid;
    place-items: center;
    width: 52px;
    height: 30px;
    border-radius: 999px;
  }
  a[aria-current='page'] .ico {
    background: var(--cobalt-soft);
  }
  .n {
    display: none;
  }
  .badge {
    position: absolute;
    top: 6px;
    left: calc(50% + 12px);
  }
  .badge.busy {
    background: var(--cobalt-soft);
    color: var(--cobalt);
  }
  .badge .spinner {
    width: 12px;
    height: 12px;
    border-width: 2px;
  }

  @media (min-width: 960px) {
    .trip-nav {
      position: sticky;
      top: calc(var(--safe-t) + 61px);
      bottom: auto;
      border-top: 0;
      border-bottom: 1px solid var(--line);
      background: var(--paper);
    }
    ol {
      max-width: 1180px;
      padding: 0 var(--gutter);
      display: flex;
      gap: 8px;
    }
    a {
      display: flex;
      align-items: center;
      gap: 10px;
      height: 56px;
      padding: 0 18px 0 12px;
      font-size: var(--fs-body);
    }
    a[aria-current='page']::before {
      top: auto;
      bottom: 0;
      left: 12px;
      right: 12px;
      border-radius: 4px 4px 0 0;
    }
    .ico {
      display: none;
    }
    .n {
      display: inline-grid;
      place-items: center;
      width: 26px;
      height: 26px;
      margin-right: 4px;
      border-radius: 50%;
      border: 2px solid currentColor;
      font-size: var(--fs-sm);
    }
    a[aria-current='page'] .n {
      background: var(--cobalt);
      border-color: var(--cobalt);
      color: var(--on-cobalt);
    }
    .badge {
      position: static;
    }
  }
</style>
