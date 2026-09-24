import { describe, expect, it } from 'vitest';
import type { EventRecord } from './api';
import { mergeLive, replaceRecord } from './feed';

const event = (id: string, action: EventRecord['action'] = 'logged') =>
	({ id, action }) as EventRecord;

const isAlert = (e: EventRecord) => e.action === 'alert';

describe('mergeLive', () => {
	it('prepends new events', () => {
		const merged = mergeLive([event('a')], event('b'));
		expect(merged.map((e) => e.id)).toEqual(['b', 'a']);
	});

	it('ignores an event it already has (stream replay after reconnect)', () => {
		const list = [event('a')];
		expect(mergeLive(list, event('a'))).toBe(list);
	});

	it('leaves out events the view excludes', () => {
		const list = [event('a', 'alert')];
		expect(mergeLive(list, event('b', 'logged'), isAlert)).toBe(list);
		expect(mergeLive(list, event('c', 'alert'), isAlert)).toHaveLength(2);
	});
});

describe('replaceRecord', () => {
	it('swaps the reviewed record in place', () => {
		const reviewed = { ...event('b'), review: 'real' } as EventRecord;
		const list = replaceRecord([event('a'), event('b'), event('c')], reviewed);
		expect(list.map((e) => e.id)).toEqual(['a', 'b', 'c']);
		expect(list[1].review).toBe('real');
	});
});
