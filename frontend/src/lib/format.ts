import type { Action } from './api';

const timeFormat = new Intl.DateTimeFormat(undefined, { timeStyle: 'medium' });
const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
	dateStyle: 'medium',
	timeStyle: 'medium'
});

export function formatTime(iso: string): string {
	return timeFormat.format(new Date(iso));
}

export function formatDateTime(iso: string): string {
	return dateTimeFormat.format(new Date(iso));
}

export function percent(value: number | null): string {
	return value === null ? '–' : `${Math.round(value * 100)}%`;
}

export const ACTION_LABELS: Record<Action, string> = {
	alert: 'Alert',
	human_review: 'Review',
	logged: 'Logged',
	dismissed: 'Dismissed'
};

export function describeDuration(seconds: number, detections: number): string {
	if (detections <= 1) return 'single frame';
	return `${detections} detections over ${seconds.toFixed(1)} s`;
}
