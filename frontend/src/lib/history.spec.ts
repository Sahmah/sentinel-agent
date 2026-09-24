import { describe, expect, it } from 'vitest';
import { previous, step, type HistoryStack } from './history';

const start: HistoryStack = { entries: [], index: -1 };

function walk(...steps: Parameters<typeof step>[1][]): HistoryStack {
	return steps.reduce(step, start);
}

describe('history mirror', () => {
	it('has nothing to go back to on the first page', () => {
		expect(previous(walk({ type: 'enter', path: '/events/abc' }))).toBeNull();
	});

	it('home -> queue -> event -> back -> back ends on home (no loop)', () => {
		let h = walk(
			{ type: 'enter', path: '/' },
			{ type: 'push', path: '/events?view=pending' },
			{ type: 'push', path: '/events/abc' }
		);
		expect(previous(h)).toBe('/events?view=pending');
		h = step(h, { type: 'popstate', path: '/events?view=pending', delta: -1 });
		expect(previous(h)).toBe('/');
		h = step(h, { type: 'popstate', path: '/', delta: -1 });
		expect(previous(h)).toBeNull();
	});

	it('a new page after going back drops the old forward entries', () => {
		let h = walk(
			{ type: 'enter', path: '/' },
			{ type: 'push', path: '/a' },
			{ type: 'popstate', path: '/', delta: -1 }
		);
		h = step(h, { type: 'push', path: '/b' });
		expect(h.entries).toEqual(['/', '/b']);
	});

	it('resyncs when the browser lands on an entry it does not know', () => {
		const h = step(walk({ type: 'enter', path: '/a' }), {
			type: 'popstate',
			path: '/before-reload',
			delta: -1
		});
		expect(h).toEqual({ entries: ['/before-reload'], index: 0 });
	});
});
