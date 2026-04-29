import {
	getRuntimeModelCatalog,
	getRuntimeModelLoadJob,
	loadRuntimeModel,
	stopRuntimeModel
} from '$lib/apis/models';
import { runtimeModelLoad } from '$lib/stores';
import { get } from 'svelte/store';

const RUNTIME_LOAD_TERMINAL_STATES = new Set(['ready', 'failed', 'cancelled']);
let restartPollRun = 0;

const RESTART_REQUIRED_PARAM_KEYS = [
	'num_ctx',
	'ctx_size',
	'num_batch',
	'batch_size',
	'num_thread',
	'threads',
	'num_gpu',
	'gpu_layers',
	'n_gpu_layers',
	'use_mmap',
	'use_mlock'
];

const normalizeParamValue = (value: unknown) => {
	if (value === null || value === undefined || value === '') {
		return undefined;
	}
	if (typeof value === 'number' || typeof value === 'boolean') {
		return value;
	}
	return String(value);
};

const asParamRecord = (params: unknown): Record<string, unknown> => {
	if (!params || typeof params !== 'object' || Array.isArray(params)) {
		return {};
	}
	return params as Record<string, unknown>;
};

const resolveModelDisplayName = (catalog: any, modelId: string) => {
	const model = (catalog?.models ?? []).find((item: any) => item?.id === modelId);
	return model?.name ?? model?.display_name ?? modelId;
};

const normalizeNumber = (value: unknown) => {
	if (typeof value !== 'number' || !Number.isFinite(value)) {
		return null;
	}
	return Math.max(0, value);
};

export const normalizeRuntimeLoadProgress = (job: any) => {
	const next = {
		...(job ?? {})
	};
	const bytesTotal = normalizeNumber(next.bytes_total);
	const bytesLoaded = normalizeNumber(next.bytes_loaded);
	const processRssBytes = normalizeNumber(next.process_rss_bytes);

	if (bytesTotal !== null) {
		next.bytes_total = bytesTotal;
	}
	if (processRssBytes !== null) {
		next.process_rss_bytes = processRssBytes;
	}
	if (bytesLoaded !== null) {
		next.bytes_loaded = bytesTotal !== null && bytesTotal > 0 ? Math.min(bytesLoaded, bytesTotal) : bytesLoaded;
	}

	if (next?.state === 'ready') {
		next.percent = 100;
		if (bytesTotal !== null && bytesTotal > 0) {
			next.bytes_loaded = bytesTotal;
		}
	} else {
		const percent = normalizeNumber(next.percent);
		if (percent !== null) {
			next.percent = Math.min(99, percent);
		}
	}

	return next;
};

export const resolveRuntimeInitialSelectedModels = ({
	selectedModels,
	activeRuntimeModelId,
	availableModels,
	hasExplicitSelection
}: {
	selectedModels: string[];
	activeRuntimeModelId?: string | null;
	availableModels: string[];
	hasExplicitSelection: boolean;
}) => {
	const availableModelIds = new Set((availableModels ?? []).filter(Boolean));
	const filteredSelectedModels = (selectedModels ?? []).filter((modelId) => availableModelIds.has(modelId));

	if (!hasExplicitSelection && activeRuntimeModelId && availableModelIds.has(activeRuntimeModelId)) {
		return [activeRuntimeModelId];
	}

	return filteredSelectedModels;
};

const mergeRuntimeLoadProgress = (job: any, displayName: string) => {
	const previous = normalizeRuntimeLoadProgress(get(runtimeModelLoad));
	let next = normalizeRuntimeLoadProgress({
		...(job ?? {}),
		display_name: displayName
	});

	if (previous?.job_id === next?.job_id) {
		const previousPercent = typeof previous?.percent === 'number' ? previous.percent : null;
		const nextPercent = typeof next?.percent === 'number' ? next.percent : null;
		if (previousPercent !== null || nextPercent !== null) {
			next.percent = Math.min(99, Math.max(previousPercent ?? 0, nextPercent ?? 0));
		}

		const previousBytes = typeof previous?.bytes_loaded === 'number' ? previous.bytes_loaded : null;
		const nextBytes = typeof next?.bytes_loaded === 'number' ? next.bytes_loaded : null;
		if (previousBytes !== null || nextBytes !== null) {
			const mergedBytesLoaded = Math.max(previousBytes ?? 0, nextBytes ?? 0);
			next.bytes_loaded =
				typeof next?.bytes_total === 'number' && next.bytes_total > 0
					? Math.min(mergedBytesLoaded, next.bytes_total)
					: mergedBytesLoaded;
		}

		if (
			(!next?.rate_bytes_per_sec || next.rate_bytes_per_sec <= 0) &&
			previous?.rate_bytes_per_sec > 0
		) {
			next.rate_bytes_per_sec = previous.rate_bytes_per_sec;
		}
		if ((!next?.eta_seconds || next.eta_seconds <= 0) && previous?.eta_seconds > 0) {
			next.eta_seconds = previous.eta_seconds;
		}
	}

	next = normalizeRuntimeLoadProgress(next);

	runtimeModelLoad.set(next);
	return next;
};

const pollRuntimeModelLoadJob = async (token: string, jobId: string, displayName: string, runId: number) => {
	while (runId === restartPollRun) {
		const job = await getRuntimeModelLoadJob(token, jobId);
		mergeRuntimeLoadProgress(job, displayName);
		if (RUNTIME_LOAD_TERMINAL_STATES.has(job?.state)) {
			return job;
		}
		await new Promise((resolve) => setTimeout(resolve, 1000));
	}
	return null;
};

export const requiresRuntimeModelRestart = (previousParams: unknown, nextParams: unknown) => {
	const previous = asParamRecord(previousParams);
	const next = asParamRecord(nextParams);

	return RESTART_REQUIRED_PARAM_KEYS.some(
		(key) => normalizeParamValue(previous[key]) !== normalizeParamValue(next[key])
	);
};

export const restartActiveRuntimeModel = async (
	token: string,
	options: {
		onFailed?: (job: any) => void;
		onCancelled?: (job: any) => void;
	} = {}
) => {
	let catalog = null;
	try {
		catalog = await getRuntimeModelCatalog(token);
	} catch (err) {
		console.warn('Runtime model catalog is not available; skipping model restart.', err);
		return { restarted: false, modelId: null, loadJobId: null };
	}

	const activeModelId = catalog?.active_model_id;
	if (!activeModelId) {
		return { restarted: false, modelId: null, loadJobId: null };
	}
	const displayName = resolveModelDisplayName(catalog, activeModelId);
	const runId = restartPollRun + 1;
	restartPollRun = runId;

	runtimeModelLoad.set({
		model_id: activeModelId,
		display_name: displayName,
		state: 'queued',
		phase: 'queued',
		percent: 0
	});

	let loadJob = null;
	try {
		await stopRuntimeModel(token, activeModelId);
		const loadResult = await loadRuntimeModel(token, activeModelId);
		const job = loadResult?.job ?? loadResult;
		loadJob = mergeRuntimeLoadProgress(job, displayName);
	} catch (err) {
		runtimeModelLoad.set({
			model_id: activeModelId,
			display_name: displayName,
			state: 'failed',
			phase: 'failed',
			error: `${err}`
		});
		throw err;
	}

	const loadJobId = loadJob?.job_id ?? null;

	if (!loadJobId || RUNTIME_LOAD_TERMINAL_STATES.has(loadJob?.state)) {
		return { restarted: true, modelId: activeModelId, loadJobId };
	}

	void pollRuntimeModelLoadJob(token, loadJobId, displayName, runId).then((finalJob) => {
		if (!finalJob || runId !== restartPollRun) {
			return;
		}
		if (finalJob.state === 'ready') {
			setTimeout(() => {
				if (runId === restartPollRun) {
					runtimeModelLoad.set(null);
				}
			}, 1500);
		} else if (finalJob.state === 'failed') {
			options.onFailed?.(finalJob);
		} else if (finalJob.state === 'cancelled') {
			options.onCancelled?.(finalJob);
		}
	}).catch((err) => {
		if (runId !== restartPollRun) {
			return;
		}
		runtimeModelLoad.set({
			model_id: activeModelId,
			display_name: displayName,
			state: 'failed',
			phase: 'failed',
			error: `${err}`
		});
		options.onFailed?.({ error: `${err}` });
	});

	return { restarted: true, modelId: activeModelId, loadJobId };
};
