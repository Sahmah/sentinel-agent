import type { DayCount } from './api';
import { localDay } from './days';

export interface DayBar {
	day: string;
	total: number;
	attention: number; // alert + human_review: what a person should look at
	routine: number; // logged + dismissed
	alert: number;
	human_review: number;
	logged: number;
	dismissed: number;
}

/** The last `n` local days, oldest first, with zeros for days without events. */
export function lastDays(days: DayCount[], n: number, today: Date = new Date()): DayBar[] {
	const byDay = new Map(days.map((d) => [d.day, d]));
	const bars: DayBar[] = [];
	for (let i = n - 1; i >= 0; i--) {
		const day = localDay(new Date(today.getFullYear(), today.getMonth(), today.getDate() - i));
		const a = byDay.get(day)?.by_action ?? {};
		const [alert, human_review, logged, dismissed] = [
			a.alert ?? 0,
			a.human_review ?? 0,
			a.logged ?? 0,
			a.dismissed ?? 0
		];
		bars.push({
			day,
			total: byDay.get(day)?.total ?? 0,
			attention: alert + human_review,
			routine: logged + dismissed,
			alert,
			human_review,
			logged,
			dismissed
		});
	}
	return bars;
}

export interface Totals {
	events: number;
	alerts: number;
	real: number;
	falseAlarms: number;
	/** Share of reviewed events that were false alarms; null when nothing was reviewed. */
	falseAlarmRate: number | null;
}

/** Totals over the last `n` local days. */
export function totalsOver(days: DayCount[], n: number, today: Date = new Date()): Totals {
	const from = localDay(new Date(today.getFullYear(), today.getMonth(), today.getDate() - n + 1));
	const recent = days.filter((d) => d.day >= from);
	const sum = (f: (d: DayCount) => number) => recent.reduce((s, d) => s + f(d), 0);
	const real = sum((d) => d.reviewed_real);
	const falseAlarms = sum((d) => d.reviewed_false_alarm);
	return {
		events: sum((d) => d.total),
		alerts: sum((d) => d.by_action.alert ?? 0),
		real,
		falseAlarms,
		falseAlarmRate: real + falseAlarms ? falseAlarms / (real + falseAlarms) : null
	};
}

/** A round axis maximum (1, 2 or 5 × 10^k) at or above `value`, split into `ticks` steps. */
export function niceMax(value: number, ticks = 4): number {
	if (value <= 0) return ticks;
	const rough = value / ticks;
	const magnitude = 10 ** Math.floor(Math.log10(rough));
	const step = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= rough)!;
	return Math.max(step, 1) * ticks;
}
