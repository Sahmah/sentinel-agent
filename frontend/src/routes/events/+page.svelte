<script lang="ts">
	import { resolve } from '$app/paths';
	import { ACTIONS, ApiError, getSummary, listEvents, type EventRecord } from '$lib/api';
	import BackLink from '$lib/components/BackLink.svelte';
	import EventCard from '$lib/components/EventCard.svelte';
	import LiveStatus from '$lib/components/LiveStatus.svelte';
	import SummaryTiles from '$lib/components/SummaryTiles.svelte';
	import { dayLabel, dayRange } from '$lib/days';
	import { mergeLive } from '$lib/feed';
	import { ACTION_LABELS } from '$lib/format';
	import { LiveFeed } from '$lib/live.svelte';
	import { notifyEvent } from '$lib/notify';
	import { belongsTo, filterParams, toQuery, VIEW_LABELS, VIEWS, type EventsFilter } from '$lib/views';

	let { data } = $props();

	// Writable deriveds: reset when the filter changes (new `data`), updated by the live feed.
	let events = $derived(data.page.events);
	let cursor = $derived(data.page.next_cursor);
	let summary = $derived(data.summary);

	let freshIds = $state(new Set<string>());
	let announcement = $state('');
	let loadingMore = $state(false);
	let loadError = $state('');

	let filter = $derived(data.filter);
	let title = $derived(
		filter.day
			? dayLabel(filter.day)
			: filter.view === 'pending'
				? 'Needs your decision'
				: 'All days'
	);

	const feed = new LiveFeed();

	function params(change: Partial<EventsFilter>) {
		return filterParams({ ...filter, ...change });
	}

	function onLive(record: EventRecord) {
		// Read inside the callback, not when connecting: the stream stays open across filters.
		const merged = mergeLive(events, record, (r) => belongsTo(r, filter));
		if (merged !== events) {
			events = merged;
			freshIds.add(record.id);
		}
		announcement = `New event: ${ACTION_LABELS[record.action]}, ${record.label}`;
		notifyEvent(record);
		getSummary(filter.day ? dayRange(filter.day) : {})
			.then((s) => (summary = s))
			.catch(() => {}); // the tiles just stay one event behind
	}

	$effect(() => feed.connect(onLive));

	async function loadMore() {
		loadingMore = true;
		loadError = '';
		try {
			const page = await listEvents({ ...toQuery(filter), cursor });
			events = [...events, ...page.events];
			cursor = page.next_cursor;
		} catch (e) {
			loadError = e instanceof ApiError ? e.message : 'Could not load more events.';
		} finally {
			loadingMore = false;
		}
	}
</script>

<svelte:head><title>{title} · Sentinel</title></svelte:head>

<LiveStatus status={feed.status} />

<BackLink fallback="/" label="Days" />
<h1>
	{title}
	{#if filter.day}<time class="muted" datetime={filter.day}>{filter.day}</time>{/if}
</h1>

<SummaryTiles {summary} />

<nav class="tabs" aria-label="Filter by your verdict">
	{#each VIEWS as view (view)}
		<a
			href={resolve(`/events?${params({ view })}`)}
			aria-current={filter.view === view ? 'page' : undefined}
			class={{ pending: view === 'pending' }}>{VIEW_LABELS[view]}</a
		>
	{/each}
</nav>

{#if filter.view !== 'pending'}
	<nav class="filters" aria-label="Filter by the system's decision">
		<span class="muted">System decided:</span>
		<a href={resolve(`/events?${params({ action: null })}`)} aria-current={filter.action === null ? 'page' : undefined}>Any</a>
		{#each ACTIONS as action (action)}
			<a href={resolve(`/events?${params({ action })}`)} aria-current={filter.action === action ? 'page' : undefined}>
				{ACTION_LABELS[action]}
			</a>
		{/each}
	</nav>
{/if}

<p class="visually-hidden" aria-live="polite">{announcement}</p>

{#if events.length === 0}
	<p class="empty">
		{#if filter.view === 'pending'}
			Nothing waiting for you{filter.day ? ' on this day' : ''}.
		{:else if filter.view === 'real' || filter.view === 'false_alarm'}
			No events marked as {VIEW_LABELS[filter.view].toLowerCase()} here yet. Open an event and use
			its Real / False alarm buttons.
		{:else}
			No events match.
		{/if}
	</p>
{:else}
	<ul class="list">
		{#each events as event (event.id)}
			<li><EventCard {event} fresh={freshIds.has(event.id)} showDate={!filter.day} /></li>
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
	h1 {
		display: flex;
		align-items: baseline;
		gap: 0.7rem;
		font-size: 1.4rem;
		margin: 0 0 1rem;
	}
	.muted {
		color: var(--muted);
		font-size: 0.85rem;
		font-weight: normal;
	}
	.tabs {
		display: flex;
		gap: 0.2rem;
		flex-wrap: wrap;
		margin: 1.4rem 0 0.8rem;
		border-bottom: 1px solid var(--border);
	}
	.tabs a {
		padding: 0.5rem 0.9rem;
		color: var(--muted);
		text-decoration: none;
		border-bottom: 3px solid transparent;
		margin-bottom: -1px;
	}
	.tabs a[aria-current='page'] {
		color: var(--text);
		font-weight: 600;
		border-bottom-color: var(--accent);
	}
	.tabs a.pending[aria-current='page'] {
		border-bottom-color: var(--review);
	}
	.filters {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		flex-wrap: wrap;
		margin: 0 0 1rem;
	}
	.filters a {
		padding: 0.25rem 0.75rem;
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
