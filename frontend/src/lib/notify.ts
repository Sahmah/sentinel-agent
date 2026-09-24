import { goto } from '$app/navigation';
import { resolve } from '$app/paths';
import type { EventRecord } from './api';
import { ACTION_LABELS } from './format';

export function notificationsSupported(): boolean {
	return typeof Notification !== 'undefined';
}

/** Call only from a click: browsers ignore or penalise unprompted requests. */
export async function enableNotifications(): Promise<NotificationPermission> {
	if (!notificationsSupported()) return 'denied';
	return Notification.requestPermission();
}

/** Notify for live events that need a person. The text stays generic on purpose:
 * no snapshot and no model output leaves the page. */
export function notifyEvent(event: EventRecord): void {
	if (!notificationsSupported() || Notification.permission !== 'granted') return;
	if (event.action !== 'alert' && event.action !== 'human_review') return;
	const where = event.entered_restricted_zone ? 'in the restricted zone' : 'outside the zone';
	const notification = new Notification(`${ACTION_LABELS[event.action]}: ${event.label}`, {
		body: `${event.camera_id}, ${where}`,
		tag: event.id // a replayed event replaces its notification instead of stacking
	});
	notification.onclick = () => {
		window.focus();
		goto(resolve('/events/[id]', { id: event.id }));
	};
}
