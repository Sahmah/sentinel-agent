// Mirrors the Python models in src/sentinel_agent/storage/base.py and
// mcp_server/tools.py. Update both sides in the same commit.

export type Action = 'alert' | 'human_review' | 'logged' | 'dismissed';
export type Severity = 'low' | 'medium' | 'high' | 'critical';
export type Verdict = 'real' | 'false_alarm';
/** A verdict, or 'unreviewed' for events nobody has given one yet. */
export type ReviewFilter = Verdict | 'unreviewed';

export interface EventRecord {
	id: string;
	run_id: string;
	source: string;
	camera_id: string;
	label: string;
	occurred_at: string; // ISO 8601, UTC
	duration_seconds: number;
	detection_count: number;
	entered_restricted_zone: boolean;
	p_cv: number;
	p_cv_calibrated: boolean;
	p_cv_raw: number | null;
	llm_confidence: number | null;
	combined_confidence: number | null;
	disagreement: boolean;
	severity: Severity | null;
	action: Action;
	reasoning: string | null;
	confidence_basis: string | null;
	triage_reason: string | null;
	is_true_positive: boolean | null;
	snapshot: string | null;
	review: Verdict | null;
	reviewed_at: string | null;
}

export interface EventPage {
	events: EventRecord[];
	next_cursor: string | null;
}

export interface EventSummary {
	total: number;
	by_action: Partial<Record<Action, number>>;
	by_label: Record<string, number>;
	disagreements: number;
	first_occurred_at: string | null;
	last_occurred_at: string | null;
	alert_ids: string[];
	reviewed: number;
	reviewed_real: number;
	reviewed_false_alarm: number;
	truncated: boolean;
}

export interface DayCount {
	day: string; // YYYY-MM-DD in the time zone the days were asked for
	total: number;
	by_action: Partial<Record<Action, number>>;
	needs_review: number;
	reviewed_real: number;
	reviewed_false_alarm: number;
	disagreements: number;
}

export interface DaysSummary {
	days: DayCount[];
	needs_review: number;
	truncated: boolean;
}

export interface EventQuery {
	action?: Action | null;
	review?: ReviewFilter | null;
	since?: string | null;
	until?: string | null;
	cursor?: string | null;
	limit?: number;
}

export const ACTIONS: Action[] = ['alert', 'human_review', 'logged', 'dismissed'];

export class ApiError extends Error {}

type Fetch = typeof fetch;

async function request<T>(fetcher: Fetch, url: string, init?: RequestInit): Promise<T> {
	let response: Response;
	try {
		response = await fetcher(url, init);
	} catch {
		throw new ApiError('Cannot reach the Sentinel API. Is `sentinel serve` running?');
	}
	const body = await response.json().catch(() => null);
	if (!response.ok) {
		throw new ApiError(body?.error ?? `${response.status} ${response.statusText}`);
	}
	return body as T;
}

export function getSummary(
	range: { since?: string | null; until?: string | null } = {},
	fetcher: Fetch = fetch
): Promise<EventSummary> {
	const query = new URLSearchParams();
	if (range.since) query.set('since', range.since);
	if (range.until) query.set('until', range.until);
	return request(fetcher, `/api/summary?${query}`);
}

export function getDays(timeZone: string, fetcher: Fetch = fetch): Promise<DaysSummary> {
	return request(fetcher, `/api/days?${new URLSearchParams({ tz: timeZone })}`);
}

export function listEvents(params: EventQuery = {}, fetcher: Fetch = fetch): Promise<EventPage> {
	const query = new URLSearchParams({ limit: String(params.limit ?? 24) });
	for (const key of ['action', 'review', 'since', 'until', 'cursor'] as const) {
		const value = params[key];
		if (value) query.set(key, value);
	}
	return request(fetcher, `/api/events?${query}`);
}

export function getEvent(id: string, fetcher: Fetch = fetch): Promise<EventRecord> {
	return request(fetcher, `/api/events/${encodeURIComponent(id)}`);
}

export function reviewEvent(id: string, verdict: Verdict): Promise<EventRecord> {
	return request(fetch, `/api/events/${encodeURIComponent(id)}/review`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ verdict })
	});
}

export function cropUrl(event: EventRecord): string | null {
	return event.snapshot ? `/api/snapshots/${event.snapshot}` : null;
}

export function sceneUrl(event: EventRecord): string | null {
	// `snapshot` is "<source>/<id>.jpg"; the full frame sits next to it as "<id>_scene.jpg".
	return event.snapshot ? `/api/snapshots/${event.snapshot.replace(/\.jpg$/, '_scene.jpg')}` : null;
}
