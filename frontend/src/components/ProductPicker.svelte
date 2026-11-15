<script lang="ts">
  // Search Grocy's products and pick one. Suggestions appear as one-tap choices.
  import { api, errorMessage } from '../lib/api';
  import type { IdName } from '../lib/types';
  import Icon from './Icon.svelte';
  import Sheet from './Sheet.svelte';

  let {
    open = $bindable(false),
    title = 'Choose a product',
    initialQuery = '',
    suggestions = [],
    onpick,
    oncreate,
  }: {
    open?: boolean;
    title?: string;
    initialQuery?: string;
    suggestions?: IdName[];
    onpick: (product: IdName) => void;
    /** When given, offers "create a new product" with the typed name. */
    oncreate?: (name: string) => void;
  } = $props();

  let query = $state('');
  let results = $state<IdName[]>([]);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let input: HTMLInputElement | undefined = $state();
  let controller: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  // Reset whenever the sheet opens.
  $effect(() => {
    if (open) {
      query = initialQuery;
      search(initialQuery, 0);
      queueMicrotask(() => input?.focus());
    }
  });

  function search(q: string, delay = 200) {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      controller?.abort();
      controller = new AbortController();
      loading = true;
      try {
        results = await api.products(q.trim(), controller.signal);
        error = null;
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        error = errorMessage(err);
      } finally {
        loading = false;
      }
    }, delay);
  }

  function pick(p: IdName) {
    open = false;
    onpick(p);
  }
</script>

<Sheet bind:open {title}>
  <div class="picker">
    {#if suggestions.length}
      <div class="suggest">
        <p class="small muted">Looks like</p>
        <div class="chips">
          {#each suggestions as s (s.id)}
            <button type="button" class="chip suggest" onclick={() => pick(s)}><Icon name="check" size={16} /> {s.name}</button>
          {/each}
        </div>
      </div>
    {/if}
    <label class="search">
      <span class="sr-only">Search products</span>
      <Icon name="search" />
      <input
        bind:this={input}
        bind:value={query}
        oninput={() => search(query)}
        type="search"
        placeholder="Search Grocy products"
        autocomplete="off"
        enterkeyhint="search"
      />
      {#if loading}<span class="spinner" aria-hidden="true"></span>{/if}
    </label>
    {#if error}<p class="form-error">{error}</p>{/if}
    <ul class="results" aria-label="Products">
      {#each results as p (p.id)}
        <li><button type="button" onclick={() => pick(p)}>{p.name}</button></li>
      {:else}
        {#if !loading && query.trim()}
          <li class="empty muted">No product in Grocy matches “{query.trim()}”.</li>
        {/if}
      {/each}
    </ul>
    {#if oncreate}
      <button
        type="button"
        class="btn block create"
        onclick={() => {
          open = false;
          oncreate?.(query.trim());
        }}
      >
        <Icon name="plus" /> Create a new product{query.trim() ? ` “${query.trim()}”` : ''}
      </button>
    {/if}
  </div>
</Sheet>

<style>
  .picker {
    display: grid;
    gap: 14px;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 6px;
  }
  .search {
    position: sticky;
    top: 0;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 14px;
    border: 2px solid var(--line);
    border-radius: var(--r-md);
    background: var(--surface);
    color: var(--ink-3);
  }
  .search:focus-within {
    border-color: var(--cobalt);
  }
  .search input {
    border: 0 !important;
    box-shadow: none !important;
    padding-inline: 0 !important;
    background: transparent !important;
  }
  .results {
    list-style: none;
    margin: 0;
    padding: 0;
    min-height: 120px;
  }
  .results button {
    width: 100%;
    min-height: 52px;
    padding: 10px 6px;
    border: 0;
    border-bottom: 1px solid var(--line);
    background: none;
    color: var(--ink);
    font: inherit;
    font-weight: 600;
    text-align: left;
    cursor: pointer;
  }
  .results button:hover,
  .results button:focus-visible {
    color: var(--cobalt);
    background: var(--cobalt-soft);
  }
  .empty {
    padding: 12px 6px;
  }
</style>
