/**
 * <input type="datetime-local"> speaks local wall time without an offset; the
 * API requires offset-aware timestamps. These convert both ways.
 */

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

/** ISO timestamp -> "YYYY-MM-DDTHH:mm" in the browser's local time. */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  return `${String(d.getFullYear())}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

/** "YYYY-MM-DDTHH:mm" (local) -> ISO 8601 in UTC, or null if blank or invalid. */
export function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

export function nowLocalInput(): string {
  return toLocalInput(new Date().toISOString());
}
