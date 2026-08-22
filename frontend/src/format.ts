/** Display-only formatting helpers.

 * Money and hour values arrive from the API as exact decimal strings
 * (design-doc.md §5.5); these helpers format them for display and never
 * compute new money values.
 */

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
});

export function formatMoney(value: string): string {
  const parsed = Number(value);
  return Number.isNaN(parsed) ? value : usd.format(parsed);
}

/** Formats an hourly rate like "25.5" -> "$25.50/hr". */
export function formatRate(value: string): string {
  return `${formatMoney(value)}/hr`;
}

/** Formats hours without inventing precision: "8.00" stays "8", "8.5" stays "8.5". */
export function formatHours(value: string): string {
  return String(Number(value));
}

const dateFmt = new Intl.DateTimeFormat('en-US', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
});

export function formatDate(iso: string): string {
  // Date-only strings are parsed as UTC midnight, so format in UTC to keep the calendar day.
  const date = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? iso : dateFmt.format(date);
}

export function formatPeriod(start: string, end: string): string {
  return `${formatDate(start)} – ${formatDate(end)}`;
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function weekdayName(weekday: number): string {
  return WEEKDAYS[weekday] ?? `day ${weekday}`;
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}
