import { resolve } from '$app/paths';
import type { AfterNavigate } from '@sveltejs/kit';
import { previous, step, type HistoryStack } from './history';

const BASE = resolve('/').replace(/\/$/, '');

class AppHistory {
	#stack = $state<HistoryStack>({ entries: [], index: -1 });

	/** Where the browser's back button would go, if that is a page of this app. */
	previous = $derived(previous(this.#stack));

	/** Call from the root layout's `afterNavigate`. */
	record(nav: AfterNavigate): void {
		if (!nav.to) return;
		// Recorded without the base path, so resolve() can add it back exactly once.
		const path = nav.to.url.pathname.slice(BASE.length) + nav.to.url.search;
		if (nav.type === 'enter') this.#stack = step(this.#stack, { type: 'enter', path });
		else if (nav.type === 'popstate')
			this.#stack = step(this.#stack, { type: 'popstate', path, delta: nav.delta });
		// Within one page, links only change tabs and filters, and those replace the
		// history entry (data-sveltekit-replacestate) instead of adding one.
		else if (nav.from?.route.id === nav.to.route.id)
			this.#stack = step(this.#stack, { type: 'replace', path });
		else this.#stack = step(this.#stack, { type: 'push', path });
	}
}

export const appHistory = new AppHistory();
