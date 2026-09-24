<script lang="ts">
	import { resolve } from '$app/paths';
	import { ApiError, cropUrl, reviewEvent, sceneUrl, type Verdict } from '$lib/api';
	import ActionBadge from '$lib/components/ActionBadge.svelte';
	import BackLink from '$lib/components/BackLink.svelte';
	import ConfidenceBar from '$lib/components/ConfidenceBar.svelte';
	import { dayLabel, localDay } from '$lib/days';
	import { ACTION_LABELS, describeDuration, formatDateTime, percent } from '$lib/format';

	let { data } = $props();

	// Writable: replaced with the API's answer after a review.
	let event = $derived(data.event);
	let saving = $state(false);
	let reviewError = $state('');

	let scene = $derived(sceneUrl(event));
	// Only human_review events are waiting on a person; on the others a review is optional feedback.
	let needsYou = $derived(event.action === 'human_review' && !event.review);
	let crop = $derived(cropUrl(event));
	let day = $derived(localDay(event.occurred_at));

	async function review(verdict: Verdict) {
		saving = true;
		reviewError = '';
		try {
			event = await reviewEvent(event.id, verdict);
		} catch (e) {
			reviewError = e instanceof ApiError ? e.message : 'Could not save the review.';
		} finally {
			saving = false;
		}
	}
</script>

<svelte:head><title>{event.label} · Sentinel</title></svelte:head>

<BackLink fallback={`/events?day=${day}`} label={dayLabel(day)} />

<header class="head">
	<ActionBadge action={event.action} />
	<h1>{event.label}</h1>
	{#if event.severity}<span class="muted">severity: {event.severity}</span>{/if}
</header>
<p class="muted">
	<time datetime={event.occurred_at}>{formatDateTime(event.occurred_at)}</time> · {event.camera_id}
	· {describeDuration(event.duration_seconds, event.detection_count)} ·
	{event.entered_restricted_zone ? 'entered the restricted zone' : 'stayed outside the zone'}
</p>

{#if scene && crop}
	<div class="images">
		<figure>
			<img src={scene} alt={`Full frame of the ${event.label} event, with its box drawn`} />
			<figcaption>Scene</figcaption>
		</figure>
		<figure>
			<img class="crop" src={crop} alt={`Close-up of the ${event.label} event`} />
			<figcaption>Crop</figcaption>
		</figure>
	</div>
{:else}
	<p class="muted">No snapshot was saved for this event.</p>
{/if}

<section class="panel">
	<h2>Why this decision</h2>
	{#if event.reasoning}
		<!-- Model output: rendered as text, never as HTML. -->
		<p>{event.reasoning}</p>
		{#if event.confidence_basis}<p class="muted">What would change its mind: {event.confidence_basis}</p>{/if}
	{:else}
		<p class="muted">
			Not sent to the agent{event.triage_reason ? `: ${event.triage_reason}` : ''}.
		</p>
	{/if}
	<div class="bars">
		<ConfidenceBar
			label="vision"
			value={event.p_cv}
			color="var(--cv)"
			note={event.p_cv_calibrated ? '' : '*'}
		/>
		<ConfidenceBar label="agent" value={event.llm_confidence} color="var(--llm)" />
		<ConfidenceBar label="fused" value={event.combined_confidence} color="var(--text)" />
	</div>
	<p class="muted small">
		{#if event.disagreement}Vision and agent disagree by more than the allowed gap, so a person
			decides.{/if}
		{#if !event.p_cv_calibrated}* raw detector score: review events to calibrate it.{/if}
		{#if event.is_true_positive !== null}Synthetic ground truth: {event.is_true_positive
				? 'real'
				: 'false positive'}.{/if}
	</p>
</section>

<section class={['panel', { needed: needsYou }]}>
	{#if needsYou}
		<h2>Needs your decision</h2>
		<p>
			{event.llm_confidence === null
				? "The agent's answer could not be used, so the system did not decide on its own."
				: event.disagreement
					? `Vision (${percent(event.p_cv)}) and the agent (${percent(event.llm_confidence)}) disagree, so the system did not decide on its own.`
					: 'The combined confidence is too uncertain for the system to decide on its own.'}
			Was it real?
		</p>
	{:else}
		<h2>Was this right? <span class="muted">(optional)</span></h2>
		<p class="muted">
			{#if event.review}
				Marked as <strong>{event.review === 'real' ? 'real' : 'a false alarm'}</strong>. You can
				change it.
			{:else}
				The system decided <strong>{ACTION_LABELS[event.action].toLowerCase()}</strong> on its own.
				Telling it whether it was right calibrates the camera's confidence (after 5 real and 5
				false alarms).
			{/if}
		</p>
	{/if}
	<div class="actions">
		<button
			onclick={() => review('real')}
			disabled={saving}
			aria-pressed={event.review === 'real'}>Real</button
		>
		<button
			onclick={() => review('false_alarm')}
			disabled={saving}
			aria-pressed={event.review === 'false_alarm'}>False alarm</button
		>
	</div>
	{#if reviewError}<p class="error" role="alert">{reviewError}</p>{/if}
</section>

<p class="muted small">
	Detector score {percent(event.p_cv_raw)} raw · event id <code>{event.id}</code>
</p>

<style>
	.head {
		display: flex;
		align-items: center;
		gap: 0.7rem;
	}
	h1 {
		margin: 0;
		text-transform: capitalize;
	}
	h2 {
		margin-top: 0;
		font-size: 1rem;
	}
	.muted {
		color: var(--muted);
	}
	.small {
		font-size: 0.8rem;
	}
	.images {
		display: grid;
		grid-template-columns: 2fr 1fr;
		gap: 0.8rem;
		margin: 1rem 0;
	}
	figure {
		margin: 0;
	}
	img {
		width: 100%;
		border-radius: var(--radius);
		border: 1px solid var(--border);
		background: var(--surface-2);
	}
	.crop {
		image-rendering: pixelated;
		max-height: 22rem;
		object-fit: contain;
	}
	figcaption {
		font-size: 0.8rem;
		color: var(--muted);
	}
	.panel {
		padding: 1rem 1.2rem;
		margin: 1rem 0;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
	}
	.bars {
		display: grid;
		gap: 0.35rem;
		max-width: 26rem;
		margin-top: 0.8rem;
	}
	.needed {
		border-color: var(--review);
		border-width: 2px;
	}
	.actions {
		display: flex;
		gap: 0.6rem;
	}
	.actions button[aria-pressed='true'] {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 15%, var(--surface));
	}
	.error {
		color: var(--alert);
	}
	@media (max-width: 40rem) {
		.images {
			grid-template-columns: 1fr;
		}
	}
</style>
