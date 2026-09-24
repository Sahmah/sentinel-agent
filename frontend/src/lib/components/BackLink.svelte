<script lang="ts">
	import { resolve } from '$app/paths';
	import type { PathnameWithSearchOrHash } from '$app/types';
	import { appHistory } from '$lib/history.svelte';
	import { pageLabel } from '$lib/views';

	/** Behaves like the browser's back button and names the page it returns to.
	 * `fallback`/`label` are only for a page opened with nothing to go back to
	 * (a pasted link, a notification, a reload). */
	let { fallback, label }: { fallback: PathnameWithSearchOrHash; label: string } = $props();

	// History entries are app paths recorded by SvelteKit's router (without the base path).
	let back = $derived(appHistory.previous as PathnameWithSearchOrHash | null);
	let text = $derived(back ? pageLabel(new URL(back, 'http://app')) : label);

	function onclick(event: MouseEvent) {
		// A plain click steps back through history, exactly like the browser's button;
		// ctrl/cmd/middle-click keeps the link's normal "open in a new tab".
		if (!back || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
		event.preventDefault();
		history.back();
	}
</script>

<p><a href={resolve(back ?? fallback)} {onclick}>← {text}</a></p>
