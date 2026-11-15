// Display helpers. Numbers come resolved from the API; these only format them.

const locale = typeof navigator !== 'undefined' ? navigator.language : 'en';

const moneyFmt = new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const qtyFmt = new Intl.NumberFormat(locale, { maximumFractionDigits: 3 });

/** Grocy's currency isn't exposed by the API, so prices are shown as plain amounts. */
export function money(value: number | null | undefined): string {
  return value == null ? '' : moneyFmt.format(value);
}

export function qty(value: number): string {
  return qtyFmt.format(value);
}

/**
 * Timestamps from the API are UTC but arrive without a zone designator
 * (SQLite drops it), so treat zone-less ones as UTC.
 */
export function parseInstant(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}

function parseDay(iso: string): Date {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d);
}

function startOfToday(): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

export function todayISO(): string {
  const d = startOfToday();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function addDaysISO(days: number): string {
  const d = startOfToday();
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** "12 Nov" (or "12 Nov 2025" when not this year). */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = iso.length > 10 ? parseInstant(iso) : parseDay(iso);
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(locale, { day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }) });
}

/** "Thu, Nov 12" style (locale order), for trip titles. */
export function longDate(iso: string): string {
  return parseInstant(iso).toLocaleDateString(locale, { weekday: 'short', day: 'numeric', month: 'short' });
}

export function dateTime(iso: string): string {
  const d = parseInstant(iso);
  return d.toLocaleString(locale, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}

/** Due date phrased for a person: "Never expires", "Due today", "Due in 5 days (17 Nov)". */
export function dueLabel(due: string): string {
  if (due === 'never') return "Doesn't expire";
  const days = Math.round((parseDay(due).getTime() - startOfToday().getTime()) / 86_400_000);
  if (days === 0) return 'Due today';
  if (days === 1) return 'Due tomorrow';
  if (days < 0) return `Due ${shortDate(due)} (past)`;
  if (days <= 14) return `Due in ${days} days`;
  return `Due ${shortDate(due)}`;
}

export function tripTitle(trip: { name: string; created_at: string }): string {
  return trip.name.trim() || `Shopping on ${longDate(trip.created_at)}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${qty(n)} ${n === 1 ? one : many}`;
}

/** Joins a list for prose: "A", "A and B", "A, B and C". */
export function listJoin(parts: string[]): string {
  if (parts.length <= 1) return parts[0] ?? '';
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}
