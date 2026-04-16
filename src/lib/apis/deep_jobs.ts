import { WEBUI_API_BASE_URL } from '$lib/constants';

export type DeepJobState = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export type DeepJobStep = {
	ts: string | null;
	level: 'info' | 'warning' | 'error';
	phase?: string | null;
	text: string;
};

export type DeepJobProgress = {
	current: number | null;
	total: number | null;
	unit: string | null;
};

export type DeepJobSnapshot = {
	job_id: string;
	chat_id: string | null;
	state: DeepJobState;
	phase: string | null;
	summary: string | null;
	progress: DeepJobProgress | null;
	steps: DeepJobStep[];
	cancel_requested: boolean;
	result_message_id: string | null;
	error: Record<string, unknown> | string | null;
	updated_at: string | null;
};

export type DeepJobResultPayload = {
	status: 'completed';
	tool_name: string;
	assistant_message: string;
	structured_result: Record<string, unknown>;
	sources: Record<string, unknown>[];
	artifacts: Record<string, unknown>[];
	embeds: Record<string, unknown>[];
	available_actions: Record<string, unknown>[];
	execution_metadata: Record<string, unknown>;
};

type DeepJobActiveResponse = {
	job: DeepJobSnapshot | null;
};

const parseApiError = async (res: Response) => {
	try {
		return await res.json();
	} catch {
		return {
			detail: res.statusText || 'Request failed',
			status: res.status
		};
	}
};

const deepJobFetch = async <T>(token: string, url: string, init: RequestInit = {}): Promise<T> => {
	let error = null;

	const res = await fetch(url, {
		...init,
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` }),
			...(init.headers ?? {})
		}
	})
		.then(async (response) => {
			if (!response.ok) {
				throw await parseApiError(response);
			}

			return response.json() as Promise<T>;
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res as T;
};

export const getDeepJob = async (
	token: string,
	jobId: string,
	signal?: AbortSignal
): Promise<DeepJobSnapshot> => {
	if (!jobId) {
		throw new Error('Missing deep-job identifier');
	}

	return await deepJobFetch<DeepJobSnapshot>(
		token,
		`${WEBUI_API_BASE_URL}/deep-jobs/${encodeURIComponent(jobId)}`,
		{
			method: 'GET',
			signal
		}
	);
};

export const cancelDeepJob = async (
	token: string,
	jobId: string,
	signal?: AbortSignal
): Promise<DeepJobSnapshot> => {
	if (!jobId) {
		throw new Error('Missing deep-job identifier');
	}

	return await deepJobFetch<DeepJobSnapshot>(
		token,
		`${WEBUI_API_BASE_URL}/deep-jobs/${encodeURIComponent(jobId)}/cancel`,
		{
			method: 'POST',
			signal
		}
	);
};

export const getDeepJobResult = async (
	token: string,
	jobId: string,
	signal?: AbortSignal
): Promise<DeepJobResultPayload> => {
	if (!jobId) {
		throw new Error('Missing deep-job identifier');
	}

	return await deepJobFetch<DeepJobResultPayload>(
		token,
		`${WEBUI_API_BASE_URL}/deep-jobs/${encodeURIComponent(jobId)}/result`,
		{
			method: 'GET',
			signal
		}
	);
};

export const recordDeepJobDelivery = async (
	token: string,
	jobId: string,
	resultMessageId: string,
	terminalEmittedAt?: string | null,
	signal?: AbortSignal
): Promise<DeepJobSnapshot> => {
	if (!jobId) {
		throw new Error('Missing deep-job identifier');
	}

	if (!resultMessageId) {
		throw new Error('Missing deep-job result message identifier');
	}

	return await deepJobFetch<DeepJobSnapshot>(
		token,
		`${WEBUI_API_BASE_URL}/deep-jobs/${encodeURIComponent(jobId)}/delivery`,
		{
			method: 'POST',
			body: JSON.stringify({
				result_message_id: resultMessageId,
				...(terminalEmittedAt ? { terminal_emitted_at: terminalEmittedAt } : {})
			}),
			signal
		}
	);
};

export const getActiveDeepJob = async (
	token: string,
	chatId: string,
	signal?: AbortSignal
): Promise<DeepJobSnapshot | null> => {
	if (!chatId) {
		return null;
	}

	const res = await deepJobFetch<DeepJobActiveResponse>(
		token,
		`${WEBUI_API_BASE_URL}/chats/${encodeURIComponent(chatId)}/deep-jobs/active`,
		{
			method: 'GET',
			signal
		}
	);

	return res?.job ?? null;
};
