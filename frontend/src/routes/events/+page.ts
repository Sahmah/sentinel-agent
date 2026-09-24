import { error } from '@sveltejs/kit';
import { ApiError, getSummary, listEvents } from '$lib/api';
import { dayRange, parseDay } from '$lib/days';
import { parseAction, parseView, toQuery, type EventsFilter } from '$lib/views';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch, url }) => {
	const params = url.searchParams;
	const filter: EventsFilter = {
		day: parseDay(params.get('day')),
		view: parseView(params.get('view')),
		action: parseAction(params.get('action'))
	};
	try {
		const [summary, page] = await Promise.all([
			getSummary(filter.day ? dayRange(filter.day) : {}, fetch),
			listEvents(toQuery(filter), fetch)
		]);
		return { filter, summary, page };
	} catch (e) {
		if (e instanceof ApiError) error(503, e.message);
		throw e;
	}
};
