<script lang="ts">
	import { resolve } from '$app/paths';
	import { ACTIONS, ApiError, getSummary, listEvents, type EventRecord } from '$lib/api';
	import EventCard from '$lib/components/EventCard.svelte';
	import SummaryTiles from '$lib/components/SummaryTiles.svelte';
	import { mergeLive } from '$lib/feed';
	import { ACTION_LABELS } from '$lib/format';
	import { LiveFeed } from '$lib/live.svelte';
	import { enableNotifications, notificationsSupported, notifyEvent } from '$lib/notify';

	let { data } = $props();

	// Writable deriveds: reset when the filter changes (new `data`), updated by the live feed.
	let events = $derived(data.page.events);
	let cursor = $derived(data.page.next_cursor);
	let summary = $derived(data.summary);

	let freshIds = $state(new Set<string>());
	let announcement = $state('');
	let loadingMore = $state(false);
	let loadError = $state('');
	let permission = $state(notificationsSupported() ? Notification.permission : 'denied');

	const feed = new LiveFeed();

	function onLive(record: EventRecord) {
		const merged = mergeLive(events, record, data.action);
		if (merged !== events) {
			events = merged;
			freshIds.add(record.id);
		}
		announcement = `New event: ${ACTION_LABELS[record.action]}, ${record.label}`;
		notifyEvent(record);
		getSummary()
			.then((s) => (summary = s))
			.catch(() => {}); // the tiles just stay one event behind
	}

	// Connecting to the event stream is exactly what effects are for: an external
	// system, closed again when the page goes away.
	$effect(() => feed.connect(onLive));

	async function loadMore() {
		loadingMore = true;
		loadError = '';
		try {
			const page = await listEvents({ action: data.action, cursor });
			events = [...events, ...page.events];
			cursor = page.next_cursor;
		} catch (e) {
			loadError = e instanceof ApiError ? e.message : 'Could not load more events.';
		} finally {
			loadingMore = false;
		}
	}

	async function askPermission() {
		permission = await enableNotifications();
	}
</script>

<div class="toolbar">
	<p class={['status', feed.status]}>
		<span class="dot" aria-hidden="true"></span>
		{feed.status === 'live'
			? 'Live'
			: feed.status === 'connecting'
				? 'Connecting…'
				: 'Reconnecting…'}
	</p>
	{#if permission === 'default'}
		<button onclick={askPermission}>Enable alerts</button>
	{:else if permission === 'granted'}
		<span class="muted">Desktop alerts on</span>
	{/if}
</div>

<SummaryTiles {summary} />

<nav class="filters" aria-label="Filter by decision">
	<a href={resolve('/')} aria-current={data.action === null ? 'page' : undefined}>All</a>
	{#each ACTIONS as action (action)}
		<a href={resolve(`/?action=${action}`)} aria-current={data.action === action ? 'page' : undefined}>
			{ACTION_LABELS[action]}
		</a>
	{/each}
</nav>

<p class="visually-hidden" aria-live="polite">{announcement}</p>

{#if events.length === 0}
	<p class="empty">
		No events yet. Run <code>uv run sentinel demo</code> or <code>sentinel webcam</code>; new events
		appear here live.
	</p>
{:else}
	<ul class="list">
		{#each events as event (event.id)}
			<li><EventCard {event} fresh={freshIds.has(event.id)} /></li>
		{/each}
	</ul>
{/if}

{#if loadError}<p class="error" role="alert">{loadError}</p>{/if}

{#if cursor}
	<button class="more" onclick={loadMore} disabled={loadingMore}>
		{loadingMore ? 'Loading…' : 'Load more'}
	</button>
{/if}

<style>
	.toolbar {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 1rem;
	}
	.status {
		display: flex;
		align-items: center;
		gap: 0.45rem;
		margin: 0;
		font-size: 0.9rem;
		color: var(--muted);
	}
	.dot {
		width: 0.6rem;
		height: 0.6rem;
		border-radius: 50%;
		background: var(--review);
	}
	.live .dot {
		background: var(--logged);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--logged) 30%, transparent);
	}
	.muted {
		color: var(--muted);
		font-size: 0.9rem;
	}
	.filters {
		display: flex;
		gap: 0.4rem;
		flex-wrap: wrap;
		margin: 1.2rem 0 1rem;
	}
	.filters a {
		padding: 0.3rem 0.8rem;
		border-radius: 999px;
		border: 1px solid var(--border);
		color: var(--text);
		text-decoration: none;
		font-size: 0.85rem;
	}
	.filters a[aria-current='page'] {
		background: var(--text);
		color: var(--bg);
		border-color: var(--text);
	}
	.list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: grid;
		gap: 0.6rem;
	}
	.empty {
		color: var(--muted);
		padding: 2rem 0;
		text-align: center;
	}
	.error {
		color: var(--alert);
	}
	.more {
		display: block;
		margin: 1rem auto;
	}
</style>
