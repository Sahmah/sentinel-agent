import { ACTIONS, type Action, type EventQuery, type EventRecord } from './api';
import { dayLabel, dayRange, localDay, parseDay } from './days';

/** The tabs of the events page. They split by what a *person* said; the system's
 * decision (alert, review, ...) is a second, independent filter on top. */
export type View = 'all' | 'pending' | 'real' | 'false_alarm';

export const VIEWS: View[] = ['all', 'pending', 'real', 'false_alarm'];

export const VIEW_LABELS: Record<View, string> = {
	all: 'All',
	pending: 'Needs you',
	real: 'Real',
	false_alarm: 'False alarms'
};

export interface EventsFilter {
	day: string | null; // YYYY-MM-DD, local; null means every day
	view: View;
	action: Action | null; // ignored in the 'pending' view, which is human_review by definition
}

export function parseView(value: string | null): View {
	return VIEWS.includes(value as View) ? (value as View) : 'all';
}

export function parseAction(value: string | null): Action | null {
	return ACTIONS.includes(value as Action) ? (value as Action) : null;
}

/** The API query for a filter. */
export function toQuery(filter: EventsFilter): EventQuery {
	const range = filter.day ? dayRange(filter.day) : {};
	switch (filter.view) {
		case 'pending':
			return { ...range, action: 'human_review', review: 'unreviewed' };
		case 'real':
		case 'false_alarm':
			return { ...range, action: filter.action, review: filter.view };
		default:
			return { ...range, action: filter.action };
	}
}

/** Whether a record belongs in the list for a filter; used for live events. */
export function belongsTo(record: EventRecord, filter: EventsFilter): boolean {
	if (filter.day && localDay(record.occurred_at) !== filter.day) return false;
	switch (filter.view) {
		case 'pending':
			return record.action === 'human_review' && !record.review;
		case 'real':
		case 'false_alarm':
			if (record.review !== filter.view) return false;
			break;
	}
	return !filter.action || record.action === filter.action;
}

/** Query parameters for a filter (no leading "?"), leaving defaults out so URLs stay short. */
export function filterParams(filter: EventsFilter): string {
	const params = new URLSearchParams();
	if (filter.day) params.set('day', filter.day);
	if (filter.view !== 'all') params.set('view', filter.view);
	if (filter.action && filter.view !== 'pending') params.set('action', filter.action);
	return params.toString();
}

/** What a "back" link to an in-app URL should say, e.g. "Needs your decision" or "Today". */
export function pageLabel(url: URL): string {
	if (url.pathname === '/') return 'Dashboard';
	if (url.pathname.startsWith('/events/')) return 'Event';
	const view = parseView(url.searchParams.get('view'));
	const day = parseDay(url.searchParams.get('day'));
	if (view === 'pending') return day ? `${dayLabel(day)} · Needs you` : 'Needs your decision';
	const where = day ? dayLabel(day) : 'All events';
	return view === 'all' ? where : `${where} · ${VIEW_LABELS[view]}`;
}
