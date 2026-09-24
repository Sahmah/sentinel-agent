<script lang="ts">
	import { resolve } from '$app/paths';
	import type { DayCount } from '$lib/api';
	import { dayLabel } from '$lib/days';
	import { lastDays, niceMax, type DayBar } from '$lib/overview';

	let { days, count = 14 }: { days: DayCount[]; count?: number } = $props();

	let bars = $derived(lastDays(days, count));
	let max = $derived(niceMax(Math.max(...bars.map((b) => b.total))));
	let ticks = $derived([0, 0.25, 0.5, 0.75, 1].map((f) => f * max));

	let width = $state(640);
	const height = 200;
	const margin = { top: 8, right: 8, bottom: 26, left: 36 };
	const GAP = 2; // surface gap between the two stacked segments
	let plotW = $derived(Math.max(0, width - margin.left - margin.right));
	const plotH = height - margin.top - margin.bottom;
	let band = $derived(plotW / bars.length);
	let barW = $derived(Math.min(24, band * 0.6));

	let hovered = $state<number | null>(null);
	let tip = $derived(hovered === null ? null : bars[hovered]);

	const y = (v: number) => margin.top + plotH - (v / max) * plotH;
	const shortDate = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' });
	const short = (day: string) => {
		const [yy, mm, dd] = day.split('-').map(Number);
		return shortDate.format(new Date(yy, mm - 1, dd));
	};

	/** Column path: square at the baseline, 4px rounded top. */
	function column(x: number, top: number, bottom: number, rounded: boolean): string {
		const h = bottom - top;
		if (h <= 0) return '';
		const r = rounded ? Math.min(4, h, barW / 2) : 0;
		return `M${x},${bottom}V${top + r}q0,-${r} ${r},-${r}h${barW - 2 * r}q${r},0 ${r},${r}V${bottom}Z`;
	}

	function segments(b: DayBar, i: number) {
		const x = margin.left + i * band + (band - barW) / 2;
		const base = y(0);
		const attTop = y(b.attention);
		const hasRoutine = b.routine > 0;
		// The routine segment sits on top; a 2px gap keeps the two fills apart.
		const routineBottom = b.attention > 0 ? attTop - GAP : base;
		return {
			x,
			attention: column(x, attTop, base, !hasRoutine),
			routine: hasRoutine ? column(x, Math.min(y(b.total), routineBottom), routineBottom, true) : ''
		};
	}

	// A date label is ~44px wide; skip labels so neighbours never touch.
	let labelEvery = $derived(Math.max(1, Math.ceil(48 / band)));
</script>

<figure class="chart">
	<figcaption>
		<strong>Events per day</strong>
		<span class="legend">
			<span><i style:background="var(--series-attention)"></i>Needs attention (alert, review)</span>
			<span><i style:background="var(--series-routine)"></i>Routine (logged, dismissed)</span>
		</span>
	</figcaption>

	<div class="plot" bind:clientWidth={width}>
		<svg {width} {height} role="img" aria-label={`Events per day over the last ${count} days; the table below has the numbers`}>
			{#each ticks as t (t)}
				<line class="grid" x1={margin.left} x2={width - margin.right} y1={y(t)} y2={y(t)} />
				<text class="axis" x={margin.left - 6} y={y(t)} dy="0.32em" text-anchor="end">{t}</text>
			{/each}
			{#each bars as b, i (b.day)}
				{@const s = segments(b, i)}
				<!-- The whole column slot is the hit target, bigger than the bar itself. -->
				<a
					href={resolve(`/events?day=${b.day}`)}
					aria-label={`${dayLabel(b.day)}: ${b.total} events, ${b.attention} needing attention`}
					onpointerenter={() => (hovered = i)}
					onpointerleave={() => (hovered = null)}
					onfocus={() => (hovered = i)}
					onblur={() => (hovered = null)}
				>
					<rect class="hit" x={margin.left + i * band} y={margin.top} width={band} height={plotH} />
					<g class={{ lifted: hovered === i }}>
						{#if s.attention}<path d={s.attention} fill="var(--series-attention)" />{/if}
						{#if s.routine}<path d={s.routine} fill="var(--series-routine)" />{/if}
					</g>
				</a>
				{#if i % labelEvery === (bars.length - 1) % labelEvery}
					<text class="axis" x={s.x + barW / 2} y={height - 8} text-anchor="middle">{short(b.day)}</text>
				{/if}
			{/each}
		</svg>

		{#if tip && hovered !== null}
			<div
				class="tooltip"
				style:left={`${Math.min(Math.max(margin.left + (hovered + 0.5) * band, 90), width - 90)}px`}
			>
				<div class="tip-day">{dayLabel(tip.day)}</div>
				<div class="row"><b>{tip.total}</b> events</div>
				<div class="row"><i style:background="var(--series-attention)"></i><b>{tip.alert}</b> alerts · <b>{tip.human_review}</b> reviews</div>
				<div class="row"><i style:background="var(--series-routine)"></i><b>{tip.logged}</b> logged · <b>{tip.dismissed}</b> dismissed</div>
			</div>
		{/if}
	</div>

	<details>
		<summary>Show as a table</summary>
		<table>
			<thead>
				<tr><th>Day</th><th>Events</th><th>Alerts</th><th>Reviews</th><th>Logged</th><th>Dismissed</th></tr>
			</thead>
			<tbody>
				{#each bars.toReversed() as b (b.day)}
					<tr>
						<td>{dayLabel(b.day)}</td><td>{b.total}</td><td>{b.alert}</td><td>{b.human_review}</td><td
							>{b.logged}</td
						><td>{b.dismissed}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</details>
</figure>

<style>
	.chart {
		margin: 0;
		padding: 0.9rem 1rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		background: var(--surface);
	}
	figcaption {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: 0.4rem 1rem;
		margin-bottom: 0.5rem;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem 1rem;
		font-size: 0.85rem;
		color: var(--muted);
	}
	.legend i,
	.row i {
		display: inline-block;
		width: 0.7rem;
		height: 0.7rem;
		border-radius: 2px;
		margin-right: 0.35rem;
		vertical-align: -0.05rem;
	}
	.row i {
		width: 0.8rem;
		height: 2px;
		vertical-align: 0.2rem;
	}
	.plot {
		position: relative;
	}
	svg {
		display: block;
		overflow: visible;
	}
	.grid {
		stroke: var(--grid);
		stroke-width: 1;
	}
	.axis {
		fill: var(--muted);
		font-size: 11px;
	}
	.hit {
		fill: transparent;
	}
	a:focus-visible .hit {
		stroke: var(--accent);
		stroke-width: 2;
	}
	.lifted {
		filter: brightness(1.12);
	}
	.tooltip {
		position: absolute;
		top: 0;
		transform: translateX(-50%);
		pointer-events: none;
		padding: 0.5rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: 8px;
		background: var(--surface);
		box-shadow: 0 4px 16px rgb(0 0 0 / 0.12);
		font-size: 0.85rem;
		white-space: nowrap;
	}
	.tip-day {
		color: var(--muted);
		margin-bottom: 0.2rem;
	}
	details {
		margin-top: 0.4rem;
		font-size: 0.85rem;
	}
	summary {
		color: var(--muted);
		cursor: pointer;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		margin-top: 0.5rem;
	}
	th,
	td {
		text-align: right;
		padding: 0.25rem 0.5rem;
		border-bottom: 1px solid var(--grid);
	}
	th:first-child,
	td:first-child {
		text-align: left;
	}
</style>
