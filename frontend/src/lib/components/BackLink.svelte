<script lang="ts">
	import { afterNavigate } from '$app/navigation';
	import { resolve } from '$app/paths';
	import type { PathnameWithSearchOrHash } from '$app/types';
	import { pageLabel } from '$lib/views';

	/** Goes back to the page the user came from; `fallback`/`label` are only used for a
	 * page opened directly (a pasted link, a notification, a reload). */
	let { fallback, label }: { fallback: PathnameWithSearchOrHash; label: string } = $props();

	let from = $state<URL | null>(null);

	afterNavigate(({ from: previous, to }) => {
		// Only arrivals from another page count: switching tabs or filters on this
		// page is also a navigation, and must not turn "back" into "previous tab".
		if (previous && previous.route.id !== to?.route.id) from = previous.url;
	});

	// The previous URL came from SvelteKit's own router, so it is an app path; strip the
	// base path it already carries so resolve() adds it exactly once.
	const base = resolve('/').replace(/\/$/, '');
	let target = $derived(
		from ? (`${from.pathname.slice(base.length)}${from.search}` as PathnameWithSearchOrHash) : fallback
	);
	let text = $derived(from ? pageLabel(from) : label);
</script>

<p><a href={resolve(target)}>← {text}</a></p>
