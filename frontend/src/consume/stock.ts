// Wording for amounts of stock, shared by the list and the action sheet.
import { dueLabel, qty } from '../lib/format';
import type { StockProduct } from '../lib/types';

export type StockAction = 'consume' | 'open';

/** "1 Piece", "3 Pieces", "0.5 kg"; just the number when the unit is unknown. */
export function amountText(p: Pick<StockProduct, 'unit' | 'unit_plural'>, n: number): string {
  const unit = n === 1 ? p.unit : p.unit_plural || p.unit;
  return unit ? `${qty(n)} ${unit}` : qty(n);
}

/** "3 Pieces, 1 opened": what's there, as one phrase. */
export function stockText(p: StockProduct): string {
  if (p.amount <= 0) return 'None in stock';
  const parts = [`${amountText(p, p.amount)} in stock`];
  if (p.amount_opened > 0) parts.push(`${qty(p.amount_opened)} opened`);
  return parts.join(', ');
}

export function dueText(p: StockProduct): string | null {
  return p.next_due_date && p.next_due_date !== 'never' ? dueLabel(p.next_due_date) : null;
}

/** Whether the next due date is today or past, for colouring it. */
export function dueSoon(p: StockProduct): boolean {
  const label = dueText(p);
  return label !== null && (label === 'Due today' || label.endsWith('(past)'));
}

/** Every word of the query appears in the name, in any order: "milk wh" finds "Whole Milk". */
export function matches(p: StockProduct, query: string): boolean {
  const name = p.name.toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => name.includes(word));
}

/** Rounds away float noise from repeated steps (0.1 + 0.2). */
export function tidy(n: number): number {
  return Math.round(n * 10000) / 10000;
}
