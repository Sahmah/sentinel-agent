import { describe, expect, it } from 'vitest';
import type { DayCount } from './api';
import { lastDays, niceMax, totalsOver } from './overview';

const today = new Date(2026, 8, 24, 10);
const day = (d: string, overrides: Partial<DayCount> = {}): DayCount => ({
	day: d,
	total: 0,
	by_action: {},
	needs_review: 0,
	reviewed_real: 0,
	reviewed_false_alarm: 0,
	disagreements: 0,
	...overrides
});

describe('lastDays', () => {
	it('fills missing days with zeros, oldest first', () => {
		const bars = lastDays(
			[
				day('2026-09-24', {
					total: 5,
					by_action: { alert: 1, human_review: 2, logged: 2 }
				})
			],
			3,
			today
		);
		expect(bars.map((b) => b.day)).toEqual(['2026-09-22', '2026-09-23', '2026-09-24']);
		expect(bars[2]).toMatchObject({ total: 5, attention: 3, routine: 2 });
		expect(bars[0].total).toBe(0);
	});
});

describe('totalsOver', () => {
	it('counts only the window, and the false alarm share of what was reviewed', () => {
		const t = totalsOver(
			[
				day('2026-09-24', {
					total: 4,
					by_action: { alert: 2 },
					reviewed_false_alarm: 3
				}),
				day('2026-09-20', { total: 1, reviewed_real: 1 }),
				day('2026-09-01', { total: 99 })
			],
			7,
			today
		);
		expect(t).toMatchObject({ events: 5, alerts: 2, real: 1, falseAlarms: 3 });
		expect(t.falseAlarmRate).toBe(0.75);
	});

	it('has no rate when nothing was reviewed', () => {
		expect(totalsOver([day('2026-09-24', { total: 2 })], 7, today).falseAlarmRate).toBeNull();
	});
});

describe('niceMax', () => {
	it('rounds up to a clean axis', () => {
		expect(niceMax(0)).toBe(4);
		expect(niceMax(3)).toBe(4);
		expect(niceMax(37)).toBe(40);
		expect(niceMax(118)).toBe(200);
	});
});
