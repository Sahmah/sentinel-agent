import type { Action, EventRecord } from './api';

/** Put a record that arrived on the live stream at the top of the list, unless the
 * list already has it (a reconnect can replay it) or the active filter excludes it. */
export function mergeLive(
	list: EventRecord[],
	record: EventRecord,
	filter: Action | null
): EventRecord[] {
	if (filter && record.action !== filter) return list;
	if (list.some((e) => e.id === record.id)) return list;
	return [record, ...list];
}

/** Replace one record (after a review) without reordering the list. */
export function replaceRecord(list: EventRecord[], record: EventRecord): EventRecord[] {
	return list.map((e) => (e.id === record.id ? record : e));
}
