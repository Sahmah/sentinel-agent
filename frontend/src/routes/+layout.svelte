<script lang="ts">
	import { resolve } from '$app/paths';
	import '../app.css';
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import { appHistory } from '$lib/history.svelte';
	import favicon from '$lib/assets/favicon.svg';

	let { children } = $props();

	// Mirror the browser history so back links can act like the back button.
	afterNavigate((nav) => appHistory.record(nav));

	let onDay = $derived(page.url.pathname === '/events' && page.url.searchParams.has('day'));
	let pendingView = $derived(
		page.url.pathname === '/events' && page.url.searchParams.get('view') === 'pending'
	);
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>Sentinel</title>
</svelte:head>

<header>
	<a class="brand" href={resolve('/')}>Sentinel</a>
	<nav aria-label="Main">
		<a href={resolve('/')} aria-current={page.url.pathname === '/' || (onDay && !pendingView) ? 'page' : undefined}
			>Days</a
		>
		<a
			href={resolve('/events')}
			aria-current={page.url.pathname === '/events' && !pendingView && !onDay
				? 'page'
				: undefined}
			>All events</a
		>
		<a href={resolve('/events?view=pending')} aria-current={pendingView ? 'page' : undefined}
			>Needs you</a
		>
	</nav>
</header>

<main>
	{@render children()}
</main>

<style>
	header {
		display: flex;
		align-items: center;
		gap: 1.5rem;
		padding: 0.8rem 1.5rem;
		border-bottom: 1px solid var(--border);
		background: var(--surface);
	}
	.brand {
		font-weight: 700;
		font-size: 1.1rem;
		color: var(--text);
		text-decoration: none;
	}
	nav {
		display: flex;
		gap: 1rem;
	}
	nav a {
		color: var(--muted);
		text-decoration: none;
		padding-bottom: 0.15rem;
		border-bottom: 2px solid transparent;
	}
	nav a[aria-current='page'] {
		color: var(--text);
		border-bottom-color: var(--accent);
	}
	main {
		max-width: 60rem;
		margin: 0 auto;
		padding: 1.5rem;
	}
</style>
