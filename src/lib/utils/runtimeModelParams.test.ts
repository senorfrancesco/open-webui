import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import {
	getRuntimeModelCatalog,
	getRuntimeModelLoadJob,
	loadRuntimeModel,
	stopRuntimeModel
} from '$lib/apis/models';
import { runtimeModelLoad } from '$lib/stores';

import {
	normalizeRuntimeLoadProgress,
	requiresRuntimeModelRestart,
	resolveRuntimeInitialSelectedModels,
	restartActiveRuntimeModel
} from './runtimeModelParams';

vi.mock('$lib/apis/models', () => ({
	getRuntimeModelCatalog: vi.fn(),
	getRuntimeModelLoadJob: vi.fn(),
	loadRuntimeModel: vi.fn(),
	stopRuntimeModel: vi.fn()
}));

const mockedGetRuntimeModelCatalog = vi.mocked(getRuntimeModelCatalog);
const mockedGetRuntimeModelLoadJob = vi.mocked(getRuntimeModelLoadJob);
const mockedLoadRuntimeModel = vi.mocked(loadRuntimeModel);
const mockedStopRuntimeModel = vi.mocked(stopRuntimeModel);

const activeCatalog = {
	active_model_id: 'qwen-14b-llm',
	models: [{ id: 'qwen-14b-llm', name: 'Qwen 14B' }]
};

const loadJob = {
	job_id: 'job-1',
	model_id: 'qwen-14b-llm',
	state: 'queued',
	phase: 'queued',
	percent: 0,
	bytes_loaded: 0,
	bytes_total: 100
};

describe('runtime model launch params', () => {
	it('requires restart for launch-time params', () => {
		expect(requiresRuntimeModelRestart({ num_ctx: 4096 }, { num_ctx: 8192 })).toBe(true);
		expect(requiresRuntimeModelRestart({ use_mmap: true }, { use_mmap: false })).toBe(true);
		expect(requiresRuntimeModelRestart({ num_gpu: 35 }, { num_gpu: 0 })).toBe(true);
	});

	it('does not require restart for request-time params', () => {
		expect(
			requiresRuntimeModelRestart(
				{ temperature: 0.2, top_p: 0.9, max_tokens: 1024 },
				{ temperature: 0.7, top_p: 0.8, max_tokens: 2048 }
			)
		).toBe(false);
	});

	it('treats null, undefined, and empty string as the same empty value', () => {
		expect(requiresRuntimeModelRestart({ num_ctx: null }, { num_ctx: undefined })).toBe(false);
		expect(requiresRuntimeModelRestart({ num_ctx: '' }, {})).toBe(false);
	});
});

describe('normalizeRuntimeLoadProgress', () => {
	it('keeps process memory separate from artifact progress', () => {
		const normalized = normalizeRuntimeLoadProgress({
			state: 'loading',
			percent: 220,
			bytes_loaded: 11 * 1024,
			bytes_total: 5 * 1024,
			process_rss_bytes: 11 * 1024
		});

		expect(normalized.bytes_loaded).toBe(5 * 1024);
		expect(normalized.bytes_total).toBe(5 * 1024);
		expect(normalized.process_rss_bytes).toBe(11 * 1024);
		expect(normalized.percent).toBe(99);
	});

	it('marks ready progress as complete', () => {
		const normalized = normalizeRuntimeLoadProgress({
			state: 'ready',
			percent: 99,
			bytes_loaded: 40,
			bytes_total: 100
		});

		expect(normalized.percent).toBe(100);
		expect(normalized.bytes_loaded).toBe(100);
	});
});

describe('resolveRuntimeInitialSelectedModels', () => {
	it('prefers active runtime model over stale defaults', () => {
		const selected = resolveRuntimeInitialSelectedModels({
			selectedModels: ['qwen-14b-llm'],
			activeRuntimeModelId: 'qwen-vl-8b',
			availableModels: ['qwen-14b-llm', 'qwen-vl-8b'],
			hasExplicitSelection: false
		});

		expect(selected).toEqual(['qwen-vl-8b']);
	});

	it('keeps explicit selection from URL, folder, or temporary session', () => {
		const selected = resolveRuntimeInitialSelectedModels({
			selectedModels: ['qwen-14b-llm'],
			activeRuntimeModelId: 'qwen-vl-8b',
			availableModels: ['qwen-14b-llm', 'qwen-vl-8b'],
			hasExplicitSelection: true
		});

		expect(selected).toEqual(['qwen-14b-llm']);
	});
});

describe('restartActiveRuntimeModel', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		vi.clearAllMocks();
		runtimeModelLoad.set(null);
		mockedGetRuntimeModelCatalog.mockResolvedValue(activeCatalog);
		mockedStopRuntimeModel.mockResolvedValue({ status: 'success' });
		mockedLoadRuntimeModel.mockResolvedValue({ job: loadJob });
	});

	afterEach(() => {
		vi.clearAllTimers();
		vi.useRealTimers();
		runtimeModelLoad.set(null);
	});

	it('stops active model, starts load job, polls until ready, and clears ready status', async () => {
		mockedGetRuntimeModelLoadJob
			.mockResolvedValueOnce({
				...loadJob,
				state: 'loading',
				phase: 'loading_memory',
				percent: 42,
				bytes_loaded: 42,
				rate_bytes_per_sec: 1024,
				eta_seconds: 30
			})
			.mockResolvedValueOnce({
				...loadJob,
				state: 'ready',
				phase: 'ready',
				percent: 100,
				bytes_loaded: 100
			});

		const result = await restartActiveRuntimeModel('token-1');

		expect(result).toEqual({
			restarted: true,
			modelId: 'qwen-14b-llm',
			loadJobId: 'job-1'
		});
		expect(mockedStopRuntimeModel).toHaveBeenCalledWith('token-1', 'qwen-14b-llm');
		expect(mockedLoadRuntimeModel).toHaveBeenCalledWith('token-1', 'qwen-14b-llm');
		expect(get(runtimeModelLoad)).toMatchObject({
			job_id: 'job-1',
			model_id: 'qwen-14b-llm',
			display_name: 'Qwen 14B',
			state: 'queued'
		});

		await vi.waitFor(() => {
			expect(get(runtimeModelLoad)).toMatchObject({
				job_id: 'job-1',
				state: 'loading',
				percent: 42,
				bytes_loaded: 42
			});
		});

		await vi.advanceTimersByTimeAsync(1000);
		expect(get(runtimeModelLoad)).toMatchObject({
			job_id: 'job-1',
			state: 'ready',
			percent: 100,
			bytes_loaded: 100
		});

		await vi.advanceTimersByTimeAsync(1500);
		expect(get(runtimeModelLoad)).toBeNull();
	});

	it('keeps failed status and calls onFailed when polling fails', async () => {
		const onFailed = vi.fn();
		mockedGetRuntimeModelLoadJob.mockResolvedValueOnce({
			...loadJob,
			state: 'failed',
			phase: 'failed',
			error: 'load failed'
		});

		await restartActiveRuntimeModel('token-1', { onFailed });

		await vi.waitFor(() => {
			expect(onFailed).toHaveBeenCalledWith(expect.objectContaining({ error: 'load failed' }));
			expect(get(runtimeModelLoad)).toMatchObject({
				job_id: 'job-1',
				state: 'failed',
				error: 'load failed'
			});
		});
	});

	it('calls onCancelled when polling returns cancelled', async () => {
		const onCancelled = vi.fn();
		mockedGetRuntimeModelLoadJob.mockResolvedValueOnce({
			...loadJob,
			state: 'cancelled',
			phase: 'cancelled'
		});

		await restartActiveRuntimeModel('token-1', { onCancelled });

		await vi.waitFor(() => {
			expect(onCancelled).toHaveBeenCalledWith(expect.objectContaining({ state: 'cancelled' }));
			expect(get(runtimeModelLoad)).toMatchObject({
				job_id: 'job-1',
				state: 'cancelled'
			});
		});
	});

	it('does not stop or load when there is no active model', async () => {
		mockedGetRuntimeModelCatalog.mockResolvedValue({ active_model_id: null, models: [] });

		const result = await restartActiveRuntimeModel('token-1');

		expect(result).toEqual({ restarted: false, modelId: null, loadJobId: null });
		expect(mockedStopRuntimeModel).not.toHaveBeenCalled();
		expect(mockedLoadRuntimeModel).not.toHaveBeenCalled();
		expect(get(runtimeModelLoad)).toBeNull();
	});

	it('marks runtime load as failed and rethrows stop or load errors', async () => {
		mockedStopRuntimeModel.mockRejectedValue(new Error('stop failed'));

		await expect(restartActiveRuntimeModel('token-1')).rejects.toThrow('stop failed');

		expect(mockedLoadRuntimeModel).not.toHaveBeenCalled();
		expect(get(runtimeModelLoad)).toMatchObject({
			model_id: 'qwen-14b-llm',
			display_name: 'Qwen 14B',
			state: 'failed',
			phase: 'failed',
			error: 'Error: stop failed'
		});
	});
});
