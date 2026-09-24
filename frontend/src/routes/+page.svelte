<script lang="ts">
	import { resolve } from '$app/paths';
	import { getDays, type EventRecord } from '$lib/api';
	import DailyChart from '$lib/components/DailyChart.svelte';
	import LiveStatus from '$lib/components/LiveStatus.svelte';
	import OverviewTiles from '$lib/components/OverviewTiles.svelte';
	import { dayLabel, viewerTimeZone } from '$lib/days';
	import { ACTION_LABELS } from '$lib/format';
	import { LiveFeed } from '$lib/live.svelte';
	import { notifyEvent } from '$lib/notify';

	let { data } = $props();

	// Writable derived: replaced when a live event makes the counts stale.
	let days = $derived(data.days);
	let announcement = $state('');

	const feed = new LiveFeed();

	function onLive(record: EventRecord) {
		announcement = `New event: ${ACTION_LABELS[record.action]}, ${record.label}`;
		notifyEvent(record);
		getDays(viewerTimeZone())
			.then((d) => (days = d))
			.catch(() => {}); // the counts just stay one event behind
	}

	// Connecting to the event stream is exactly what effects are for: an external
	// system, closed again when the page goes away.
	$effect(() => feed.connect(onLive));
</script>

<LiveStatus status={feed.status} />

<p class="visually-hidden" aria-live="polite">{announcement}</p>

{#if days.days.length === 0}
	<p class="empty">
		No events yet. Run <code>uv run sentinel demo</code> or <code>sentinel webcam</code>; new events
		appear here live.
	</p>
{:else}
	<OverviewTiles {days} />
	<div class="gap"></div>
	<DailyChart days={days.days} />

	<h1>Days</h1>
	<ul class="days">
		{#each days.days as day (day.day)}
			<li>
				<a class="day" href={resolve(`/events?day=${day.day}`)}>
					<span class="title">
						<strong>{dayLabel(day.day)}</strong>
						<time class="muted" datetime={day.day}>{day.day}</time>
					</span>
					<span class="counts">
						<span>{day.total} {day.total === 1 ? 'event' : 'events'}</span>
						{#if day.by_action.alert}
							<span class="alert"
								>{day.by_action.alert} {day.by_action.alert === 1 ? 'alert' : 'alerts'}</span
							>
						{:else}
							<span class="muted-count">no alerts</span>
						{/if}
						{#if day.needs_review > 0}
							<span class="needs">{day.needs_review} need you</span>
						{/if}
					</span>
					<span class="verdicts">
						<span>✓ {day.reviewed_real} real</span>
						<span>✗ {day.reviewed_false_alarm} false alarms</span>
					</span>
				</a>
			</li>
		{/each}
	</ul>
	{#if days.truncated}
		<p class="muted">Only the most recent 5,000 events are counted; older days may be missing.</p>
	{/if}
	<p><a href={resolve('/events')}>Every event, newest first →</a></p>
{/if}

<style>
	h1 {
		font-size: 1.1rem;
		margin: 1.4rem 0 0.7rem;
	}
	.gap {
		height: 0.8rem;
	}
	.days {
		list-style: none;
		padding: 0;
		margin: 0;
		display: grid;
		gap: 0.6rem;
	}
	.day {
		display: grid;
		grid-template-columns: minmax(12rem, 1.4fr) 2fr 1.4fr;
		align-items: center;
		gap: 0.8rem;
		padding: 0.9rem 1rem;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
		box-shadow: var(--shadow);
		color: inherit;
		text-decoration: none;
	}
	.day:hover {
		border-color: var(--accent);
	}
	.title {
		display: grid;
	}
	.counts,
	.verdicts {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem 0.9rem;
		font-size: 0.9rem;
	}
	.verdicts {
		color: var(--muted);
	}
	.alert {
		color: var(--alert);
	}
	.muted-count {
		color: var(--muted);
	}
	.needs {
		color: var(--review);
		font-weight: 600;
	}
	.muted {
		color: var(--muted);
		font-size: 0.85rem;
	}
	.empty {
		color: var(--muted);
		padding: 2rem 0;
		text-align: center;
	}
	@media (max-width: 40rem) {
		.day {
			grid-template-columns: 1fr;
			gap: 0.4rem;
		}
	}
</style>
