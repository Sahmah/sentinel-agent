import { describe, expect, it } from 'vitest';
import type { EventRecord } from './api';
import { dayLabel, dayRange, localDay, parseDay } from './days';
import { belongsTo, filterParams, pageLabel, parseView, toQuery } from './views';

const record = (overrides: Partial<EventRecord> = {}) =>
	({
		id: 'a',
		action: 'human_review',
		review: null,
		occurred_at: new Date(2026, 8, 24, 15, 0).toISOString(),
		...overrides
	}) as EventRecord;

describe('days', () => {
	it('round-trips a local day through its UTC range', () => {
		const { since, until } = dayRange('2026-09-24');
		expect(localDay(since)).toBe('2026-09-24');
		expect(localDay(until)).toBe('2026-09-24');
		expect(new Date(until).getTime() - new Date(since).getTime()).toBe(86_400_000 - 1);
	});

	it('rejects days that are not real dates', () => {
		expect(parseDay('2026-02-30')).toBeNull();
		expect(parseDay('yesterday')).toBeNull();
		expect(parseDay('2026-09-24')).toBe('2026-09-24');
	});

	it('names today and yesterday', () => {
		const today = new Date(2026, 8, 24, 10);
		expect(dayLabel('2026-09-24', today)).toBe('Today');
		expect(dayLabel('2026-09-23', today)).toBe('Yesterday');
		expect(dayLabel('2026-09-20', today)).not.toMatch(/Today|Yesterday/);
	});
});

describe('views', () => {
	it('the pending view is unreviewed human_review, whatever the action filter', () => {
		const query = toQuery({ day: null, view: 'pending', action: 'alert' });
		expect(query).toEqual({ action: 'human_review', review: 'unreviewed' });
	});

	it('verdict tabs combine with the action filter and the day', () => {
		const query = toQuery({ day: '2026-09-24', view: 'real', action: 'alert' });
		expect(query).toMatchObject({ action: 'alert', review: 'real' });
		expect(query.since).toBe(dayRange('2026-09-24').since);
	});

	it('decides where a live event belongs', () => {
		const all = { day: '2026-09-24', view: 'all' as const, action: null };
		expect(belongsTo(record(), all)).toBe(true);
		expect(belongsTo(record(), { ...all, day: '2026-09-23' })).toBe(false);
		expect(belongsTo(record(), { ...all, view: 'pending' })).toBe(true);
		expect(belongsTo(record({ review: 'real' }), { ...all, view: 'pending' })).toBe(false);
		expect(belongsTo(record(), { ...all, view: 'real' })).toBe(false);
		expect(belongsTo(record(), { ...all, action: 'alert' })).toBe(false);
	});

	it('keeps URLs short and ignores unknown views', () => {
		expect(filterParams({ day: null, view: 'all', action: null })).toBe('');
		expect(filterParams({ day: '2026-09-24', view: 'pending', action: 'alert' })).toBe(
			'day=2026-09-24&view=pending'
		);
		expect(parseView('bogus')).toBe('all');
	});
});

describe('pageLabel', () => {
	const label = (path: string) => pageLabel(new URL(path, 'http://x'));

	it('names the page a back link returns to', () => {
		expect(label('/')).toBe('Dashboard');
		expect(label('/events?view=pending')).toBe('Needs your decision');
		expect(label('/events')).toBe('All events');
		expect(label('/events?view=false_alarm')).toBe('All events · False alarms');
		expect(label('/events?day=2026-09-20&view=real')).toMatch(/ · Real$/);
	});
});
