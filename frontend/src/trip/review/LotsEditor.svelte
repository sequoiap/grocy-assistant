<script lang="ts">
  // Due dates for an item, piece by piece: "2 due 1 Dec, 1 due 3 Mar, the other 3 on
  // the product's usual shelf life". Each lot becomes its own stock entry in Grocy.
  import { qty } from '../../lib/format';
  import type { ItemOut, Lot } from '../../lib/types';
  import Icon from '../../components/Icon.svelte';
  import DueField from './DueField.svelte';

  let {
    item,
    onlots,
    ondue,
  }: {
    item: ItemOut;
    /** Replace the item's lots ([] removes them all). */
    onlots: (lots: Lot[]) => void;
    /** The due date of the rest; null = the product's default. */
    ondue: (v: string | null) => void;
  } = $props();

  const uid = $props.id();
  // A date being added: only saved once it has a date, so none is ever made up.
  let draft = $state<{ amount: number } | null>(null);
  let draftDate: HTMLInputElement | undefined = $state();
  const unit = $derived(item.pack_factor !== 1 && item.pack_unit ? item.pack_unit : item.stock_unit);

  function amountFrom(e: Event): number | null {
    const n = Number((e.currentTarget as HTMLInputElement).value.replace(',', '.'));
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  function change(index: number, patch: Partial<Lot>) {
    onlots(item.lots.map((lot, i) => (i === index ? { ...lot, ...patch } : lot)));
  }

  function remove(index: number) {
    onlots(item.lots.filter((_, i) => i !== index));
  }

  function add() {
    draft = { amount: 1 };
    // Straight to the calendar where the browser allows it.
    requestAnimationFrame(() => {
      draftDate?.focus();
      try {
        draftDate?.showPicker();
      } catch {
        /* focus is enough */
      }
    });
  }

  function commitDraft(date: string) {
    if (!draft || !date) return;
    // Taken out of the rest when there is any left; otherwise it's one more piece.
    onlots([...item.lots, { amount: draft.amount, due_date: date }]);
    draft = null;
  }
</script>

<div class="lots">
  {#if item.lots.length === 0 && !draft}
    <DueField value={item.due_date} source={item.due_source} onchange={ondue} />
  {:else}
    <p class="head">Due dates</p>
    <div class="cols small muted" aria-hidden="true"><span>How many</span><span>Due date</span></div>
    <ul>
      {#each item.lots as lot, i (i)}
        <li class="lot">
          <input
            class="amount"
            type="number"
            inputmode="decimal"
            min="0"
            step="any"
            aria-label="How many are due on this date"
            value={lot.amount}
            onchange={(e) => {
              const n = amountFrom(e);
              if (n != null) change(i, { amount: n });
            }}
          />
          <span class="times" aria-hidden="true">×</span>
          <input
            id="{uid}-lot-{i}"
            class="date"
            type="date"
            aria-label="Due date"
            value={lot.due_date === 'never' ? '' : lot.due_date}
            onchange={(e) => {
              const v = e.currentTarget.value;
              if (v) change(i, { due_date: v });
            }}
          />
          <button type="button" class="btn ghost icon small" aria-label="Remove this date" onclick={() => remove(i)}>
            <Icon name="x" size={18} />
          </button>
        </li>
      {/each}
      {#if draft}
        <li class="lot draft">
          <input
            class="amount"
            type="number"
            inputmode="decimal"
            min="0"
            step="any"
            aria-label="How many are due on the new date"
            value={draft.amount}
            onchange={(e) => {
              const n = amountFrom(e);
              if (n != null && draft) draft.amount = n;
            }}
          />
          <span class="times" aria-hidden="true">×</span>
          <input
            bind:this={draftDate}
            class="date"
            type="date"
            aria-label="Due date for these"
            onchange={(e) => commitDraft(e.currentTarget.value)}
          />
          <button type="button" class="btn ghost icon small" aria-label="Don't add this date" onclick={() => (draft = null)}>
            <Icon name="x" size={18} />
          </button>
        </li>
        <li class="small draft-hint">Pick the date to add it.</li>
      {/if}
    </ul>
    {#if item.rest_amount > 0 && (item.lots.length > 0 || draft)}
      <DueField
        legend={`The other ${qty(item.rest_amount)} ${unit.toLowerCase()}`}
        value={item.due_date}
        source={item.due_source}
        onchange={ondue}
      />
    {/if}
  {/if}
  <button type="button" class="btn ghost small add" onclick={add} disabled={draft !== null}>
    <Icon name="plus" size={18} />
    {item.rest_amount > 1 || item.lots.length ? 'Some have another date' : 'Another one, with its own date'}
  </button>
</div>

<style>
  .lots {
    display: grid;
    gap: 8px;
    min-width: 0;
  }
  .head {
    font-weight: 650;
    font-size: var(--fs-sm);
    color: var(--ink-2);
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 8px;
  }
  .lot,
  .cols {
    display: grid;
    grid-template-columns: 4.5rem auto minmax(0, 1fr) var(--tap);
    align-items: center;
    gap: 8px;
  }
  .cols span:last-child {
    grid-column: 3;
  }
  .draft .date {
    border-color: var(--cobalt);
  }
  .draft-hint {
    color: var(--cobalt);
    font-weight: 650;
  }
  .amount {
    text-align: center;
  }
  .times {
    color: var(--ink-3);
    font-weight: 700;
  }
  .date {
    min-width: 0;
    width: 100%;
  }
  .add {
    justify-self: start;
  }
</style>
