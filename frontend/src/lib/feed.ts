import type { EventRecord } from './api';

/** Put a record that arrived on the live stream at the top of the list, unless the
 * list already has it (a reconnect can replay it) or the view it is shown in excludes it. */
export function mergeLive(
	list: EventRecord[],
	record: EventRecord,
	belongs: (record: EventRecord) => boolean = () => true
): EventRecord[] {
	if (!belongs(record)) return list;
	if (list.some((e) => e.id === record.id)) return list;
	return [record, ...list];
}

/** Replace one record (after a review) without reordering the list. */
export function replaceRecord(list: EventRecord[], record: EventRecord): EventRecord[] {
	return list.map((e) => (e.id === record.id ? record : e));
}
