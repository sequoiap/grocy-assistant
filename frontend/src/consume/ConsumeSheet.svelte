<script lang="ts">
  // One product, and how much of it to consume or open. Books straight into Grocy.
  import { api } from '../lib/api';
  import { qty } from '../lib/format';
  import { reportError } from '../lib/ui.svelte';
  import type { StockActionOut, StockProduct } from '../lib/types';
  import Icon from '../components/Icon.svelte';
  import Sheet from '../components/Sheet.svelte';
  import { amountText, dueSoon, dueText, stockText, tidy, type StockAction } from './stock';

  let {
    product = $bindable(null),
    amount = $bindable(1),
    ondone,
  }: {
    /** The product being acted on; the sheet is open while this is set. */
    product?: StockProduct | null;
    amount?: number;
    ondone: (action: StockAction, amount: number, spoiled: boolean, result: StockActionOut) => void;
  } = $props();

  let spoiled = $state(false);
  let busy = $state<StockAction | null>(null);

  // Fresh choices for every product shown.
  let shownId: number | null = null;
  $effect(() => {
    const id = product?.id ?? null;
    if (id !== shownId) {
      shownId = id;
      spoiled = false;
    }
  });

  const unopened = $derived(product ? tidy(product.amount - product.amount_opened) : 0);
  const blocked = $derived(!product || product.amount <= 0 || product.tare_weight_handling);
  const problem = $derived.by((): string | null => {
    if (!product || blocked) return null;
    if (!(amount > 0)) return 'Enter how much.';
    if (amount > product.amount)
      return product.stock_entry_id
        ? `This package holds only ${amountText(product, product.amount)}.`
        : `There's only ${amountText(product, product.amount)} in stock.`;
    return null;
  });
  const canOpen = $derived(!blocked && !problem && !spoiled && amount <= unopened);

  // Ways to set the amount in one tap, besides − and + (and besides the amount it starts at).
  const presets = $derived.by(() => {
    if (!product || blocked) return [];
    const p = product;
    const start = Math.min(p.quick_consume_amount || 1, p.amount);
    const out: { label: string; value: number }[] = [];
    const add = (label: string, value: number) => {
      if (value > 0 && value <= p.amount && value !== start && !out.some((o) => o.value === value))
        out.push({ label, value });
    };
    if (p.pack_amount) add(`Whole pack (${qty(p.pack_amount)})`, p.pack_amount);
    if (unopened > 0 && unopened < p.amount) add(`All unopened (${qty(unopened)})`, unopened);
    add(`All (${qty(p.amount)})`, p.amount);
    if (out.length) out.unshift({ label: qty(start), value: start });
    return out;
  });

  // − and + move by one; a part of one (half a bag) is typed in. Never down to nothing.
  function bump(delta: number) {
    if (!product) return;
    const next = tidy((Number.isFinite(amount) ? amount : 0) + delta);
    if (next > 0) amount = Math.min(product.amount, next);
  }

  async function act(action: StockAction) {
    if (!product || busy) return;
    const p = product;
    const n = amount;
    busy = action;
    try {
      const body = { amount: n, stock_entry_id: p.stock_entry_id };
      const result =
        action === 'consume' ? await api.consume(p.id, { ...body, spoiled }) : await api.openStock(p.id, body);
      ondone(action, n, action === 'consume' && spoiled, result);
      product = null;
    } catch (err) {
      reportError(err);
    } finally {
      busy = null;
    }
  }
</script>

<Sheet bind:open={() => product !== null, (v) => !v && (product = null)} title={product?.name ?? ''}>
  {#if product}
    {@const due = dueText(product)}
    <div class="body">
      <p class="facts">
        <span class="stock">{stockText(product)}</span>
        {#if due}<span class:soon={dueSoon(product)}>{due}</span>{/if}
        {#if product.location}<span class="muted">{product.location}</span>{/if}
      </p>

      {#if product.stock_entry_id && !blocked}
        <p class="note"><Icon name="qr" size={18} /> Scanned from a Grocy label, so only that package is used.</p>
      {/if}

      {#if product.amount <= 0}
        <p class="note warn">
          <Icon name="info" size={18} />
          <span>
            {#if product.stock_entry_id}
              Grocy has nothing left of this package, so there's nothing to consume or open. If it's here after all, use
              <strong>Search</strong> to find the product instead.
            {:else}
              Grocy has none of this in stock, so there's nothing to consume or open.
            {/if}
          </span>
        </p>
      {:else if product.tare_weight_handling}
        <p class="note warn">
          <Icon name="info" size={18} />
          <span>This product is weighed in its container. Consume it in Grocy itself, where you can enter the weight.</span>
        </p>
      {:else}
        <div class="amount">
          <span class="label" id="amount-label">How much</span>
          <div class="stepper" role="group" aria-labelledby="amount-label">
            <button type="button" aria-label="Less" disabled={!(amount > 1)} onclick={() => bump(-1)}>
              <Icon name="minus" />
            </button>
            <input
              type="number"
              inputmode="decimal"
              min="0"
              max={product.amount}
              step="any"
              bind:value={amount}
              aria-labelledby="amount-label"
            />
            <button type="button" aria-label="More" disabled={amount >= product.amount} onclick={() => bump(1)}>
              <Icon name="plus" />
            </button>
          </div>
          <span class="unit">{amount === 1 ? product.unit : product.unit_plural}</span>
        </div>
        {#if presets.length}
          <div class="presets">
            {#each presets as p (p.value)}
              <button type="button" class="chip" class:suggest={p.value === amount} onclick={() => (amount = p.value)}>
                {p.label}
              </button>
            {/each}
          </div>
        {/if}
        {#if problem}<p class="form-error" role="alert">{problem}</p>{/if}

        <label class="spoiled">
          <input type="checkbox" bind:checked={spoiled} />
          <span>It went bad: throw it out <span class="muted">(logged as spoiled)</span></span>
        </label>

        <div class="actions" class:single={!product.can_open}>
          {#if product.can_open}
            <button
              type="button"
              class="btn big"
              disabled={!canOpen || busy !== null}
              onclick={() => act('open')}
              title={unopened <= 0 ? 'All of it is open already' : undefined}
            >
              {#if busy === 'open'}<span class="spinner"></span>{/if}
              Open {problem ? '' : amountText(product, amount)}
            </button>
          {/if}
          <button
            type="button"
            class="btn big"
            class:primary={!spoiled}
            class:danger={spoiled}
            disabled={problem !== null || busy !== null}
            onclick={() => act('consume')}
          >
            {#if busy === 'consume'}<span class="spinner"></span>{:else}<Icon name={spoiled ? 'trash' : 'bowl'} />{/if}
            {spoiled ? 'Throw out' : 'Consume'} {problem ? '' : amountText(product, amount)}
          </button>
        </div>
        {#if unopened <= 0 && product.can_open}
          <p class="small muted">{product.stock_entry_id ? 'This package is open already.' : 'All of it is open already.'}</p>
        {/if}
      {/if}
    </div>
  {/if}
</Sheet>

<style>
  .body {
    display: grid;
    gap: 16px;
  }
  .facts {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 14px;
  }
  .stock {
    font-weight: 700;
  }
  .soon {
    color: var(--tomato);
    font-weight: 700;
  }
  .amount {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px 12px;
  }
  .label {
    width: 100%;
    font-weight: 650;
    font-size: var(--fs-sm);
    color: var(--ink-2);
  }
  .stepper {
    display: inline-flex;
    align-items: center;
    border-radius: var(--r-md);
    background: var(--surface-2);
    box-shadow: inset 0 -3px 0 rgba(18, 28, 58, 0.08);
  }
  .stepper button {
    display: grid;
    place-items: center;
    width: 56px;
    height: 56px;
    border: 0;
    background: transparent;
    color: var(--cobalt);
    border-radius: var(--r-md);
    cursor: pointer;
    touch-action: manipulation;
  }
  .stepper button:active:not(:disabled) {
    background: var(--cobalt-soft);
  }
  .stepper button:disabled {
    color: var(--ink-3);
    opacity: 0.45;
    cursor: default;
  }
  /* More specific than app.css's full-width input rule, so it never depends on stylesheet order. */
  .amount .stepper input {
    flex: none;
    width: 5.5ch;
    min-height: 48px;
    padding: 4px;
    text-align: center;
    font-size: var(--fs-lg);
    font-weight: 760;
    border-color: transparent;
    background: var(--surface);
    appearance: textfield;
    -moz-appearance: textfield;
  }
  .stepper input::-webkit-inner-spin-button,
  .stepper input::-webkit-outer-spin-button {
    -webkit-appearance: none;
    margin: 0;
  }
  .unit {
    font-weight: 650;
  }
  .presets {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .spoiled {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: var(--tap);
    cursor: pointer;
  }
  .spoiled input {
    flex: none;
    width: 22px;
    height: 22px;
    accent-color: var(--tomato);
  }
  .actions {
    display: grid;
    grid-template-columns: 1fr 1.4fr;
    gap: 10px;
  }
  .actions.single {
    grid-template-columns: 1fr;
  }
  .actions .btn {
    padding-inline: 0.8rem;
    font-size: var(--fs-body);
  }
</style>
