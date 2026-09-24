/** A mirror of the browser's history inside the app, so a "back" link can behave
 * exactly like the browser's back button and still say where it goes. */

export interface HistoryStack {
	entries: string[]; // in-app paths with their query, oldest first
	index: number; // the current entry; -1 before the first navigation
}

export type Step =
	| { type: 'enter'; path: string }
	| { type: 'push'; path: string }
	| { type: 'replace'; path: string }
	| { type: 'popstate'; path: string; delta: number };

export function step(stack: HistoryStack, s: Step): HistoryStack {
	if (s.type === 'enter') return { entries: [s.path], index: 0 };
	if (s.type === 'replace') {
		const entries = [...stack.entries];
		entries[Math.max(stack.index, 0)] = s.path;
		return { entries, index: Math.max(stack.index, 0) };
	}
	if (s.type === 'push') {
		// A new page drops whatever was "forward" of the current one, as the browser does.
		const entries = [...stack.entries.slice(0, stack.index + 1), s.path];
		return { entries, index: entries.length - 1 };
	}
	const index = stack.index + s.delta;
	if (index < 0 || index >= stack.entries.length || stack.entries[index] !== s.path) {
		// Moved to an entry from before this page load (or the mirror drifted): start over there.
		return { entries: [s.path], index: 0 };
	}
	return { ...stack, index };
}

/** The entry "back" would return to, or null if there is none inside the app. */
export function previous(stack: HistoryStack): string | null {
	return stack.index > 0 ? stack.entries[stack.index - 1] : null;
}
