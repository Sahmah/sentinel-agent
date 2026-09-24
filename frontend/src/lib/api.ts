// Mirrors the Python models in src/sentinel_agent/storage/base.py and
// mcp_server/tools.py. Update both sides in the same commit.

export type Action = 'alert' | 'human_review' | 'logged' | 'dismissed';
export type Severity = 'low' | 'medium' | 'high' | 'critical';
export type Verdict = 'real' | 'false_alarm';

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

export function getSummary(fetcher: Fetch = fetch): Promise<EventSummary> {
	return request(fetcher, '/api/summary');
}

export function listEvents(
	params: { action?: Action | null; cursor?: string | null; limit?: number } = {},
	fetcher: Fetch = fetch
): Promise<EventPage> {
	const query = new URLSearchParams({ limit: String(params.limit ?? 24) });
	if (params.action) query.set('action', params.action);
	if (params.cursor) query.set('cursor', params.cursor);
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
	return event.snapshot ? `/api/snapshots/${event.id}_scene.jpg` : null;
}
