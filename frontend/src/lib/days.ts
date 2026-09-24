/** Calendar days in the viewer's time zone. The API stores UTC; the dashboard groups
 * by the viewer's clock, and sends its time zone so the server's per-day counts agree. */

export function viewerTimeZone(): string {
	return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function pad(n: number): string {
	return String(n).padStart(2, '0');
}

/** The local calendar day (YYYY-MM-DD) an ISO timestamp falls on. */
export function localDay(iso: string | Date): string {
	const d = typeof iso === 'string' ? new Date(iso) : iso;
	return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Validate a YYYY-MM-DD string from the URL; null when it isn't a real date. */
export function parseDay(value: string | null): string | null {
	if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
	const [y, m, d] = value.split('-').map(Number);
	const date = new Date(y, m - 1, d);
	return date.getMonth() === m - 1 && date.getDate() === d ? value : null;
}

/** First and last instant of a local day, as UTC ISO strings (both inclusive, like the API). */
export function dayRange(day: string): { since: string; until: string } {
	const [y, m, d] = day.split('-').map(Number);
	return {
		since: new Date(y, m - 1, d, 0, 0, 0, 0).toISOString(),
		until: new Date(y, m - 1, d, 23, 59, 59, 999).toISOString()
	};
}

const dayFormat = new Intl.DateTimeFormat(undefined, {
	weekday: 'long',
	day: 'numeric',
	month: 'long'
});
const dayWithYearFormat = new Intl.DateTimeFormat(undefined, {
	weekday: 'long',
	day: 'numeric',
	month: 'long',
	year: 'numeric'
});

/** "Today", "Yesterday", or the date (with the year only when it isn't this year).
 * `today` is injectable for tests. */
export function dayLabel(day: string, today: Date = new Date()): string {
	const [y, m, d] = day.split('-').map(Number);
	const date = new Date(y, m - 1, d);
	if (day === localDay(today)) return 'Today';
	const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
	if (day === localDay(yesterday)) return 'Yesterday';
	return (y === today.getFullYear() ? dayFormat : dayWithYearFormat).format(date);
}
