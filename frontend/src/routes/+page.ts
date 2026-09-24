import { error } from '@sveltejs/kit';
import { ApiError, getDays } from '$lib/api';
import { viewerTimeZone } from '$lib/days';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ fetch }) => {
	try {
		return { days: await getDays(viewerTimeZone(), fetch) };
	} catch (e) {
		if (e instanceof ApiError) error(503, e.message);
		throw e;
	}
};
