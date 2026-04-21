<script lang="ts">
	import { browser } from '$app/environment';
	import { getContext, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nType } from 'i18next';

	import { createDeepJobStore, getCachedDeepJobSnapshot } from '$lib/stores/deepJobs';
	import type {
		DeepJobProgress,
		DeepJobSnapshot,
		DeepJobState,
		DeepJobStep
	} from '$lib/apis/deep_jobs';

	const i18n = getContext<Writable<I18nType>>('i18n');

	export let jobId = '';
	export let title = 'Long-running tool';
	export let toolLabel: string | null = null;
	export let initialSummary = 'Long-running tool';
	export let initialState: DeepJobState = 'queued';
	export let resultMessageId: string | null = null;

	const initialSnapshot: DeepJobSnapshot | null =
		jobId === ''
			? null
			: {
					job_id: jobId,
					chat_id: null,
					state: initialState,
					tool_label: toolLabel,
					phase: null,
					summary: initialSummary,
					progress: null,
					steps: [],
					cancel_requested: false,
					result_message_id: resultMessageId,
					error: null,
					updated_at: null
			  };

	const deepJobStore = createDeepJobStore({
		token: browser ? (localStorage.token ?? '') : '',
		jobId,
		initialSnapshot: getCachedDeepJobSnapshot(jobId) ?? initialSnapshot
	});

	let expanded = false;

	const STATE_CLASSNAMES: Record<DeepJobState, string> = {
		queued: 'border-gray-200 bg-gray-100 text-gray-700 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-200',
		running: 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/70 dark:bg-blue-950/60 dark:text-blue-300',
		completed: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/70 dark:bg-emerald-950/60 dark:text-emerald-300',
		failed: 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/70 dark:bg-red-950/60 dark:text-red-300',
		cancelled: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/70 dark:bg-amber-950/60 dark:text-amber-300'
	};

	const STEP_LEVEL_CLASSNAMES: Record<DeepJobStep['level'], string> = {
		info: 'bg-blue-500 dark:bg-blue-400',
		warning: 'bg-amber-500 dark:bg-amber-400',
		error: 'bg-red-500 dark:bg-red-400'
	};

	const isTerminalState = (state: DeepJobState | null | undefined) =>
		state === 'completed' || state === 'failed' || state === 'cancelled';

	type LongRunningToolDisplayLocale = 'ru' | 'en';

	const getDisplayLocale = (): LongRunningToolDisplayLocale =>
		String($i18n?.language || 'en-US')
			.toLowerCase()
			.startsWith('ru')
			? 'ru'
			: 'en';

	const getCanonicalLongRunningToolLabel = () =>
		getDisplayLocale() === 'ru' ? 'Инструмент долгого выполнения' : 'Long-running tool';

	const LEGACY_TOOL_LABEL_TEXT_PAIRS: Array<[string, string]> = [
		['Вопрос по документу', 'Document question'],
		['Быстрый анализ документа', 'Quick document analysis'],
		['Глубокий анализ документа', 'Deep document analysis'],
		['Сравнение документов', 'Document comparison'],
		['Глубокое сравнение документов', 'Deep document comparison'],
		['Быстрый анализ оборудования', 'Quick equipment analysis'],
		['Глубокий анализ оборудования', 'Deep equipment analysis'],
		['Анализ оборудования', 'Equipment analysis']
	];

	const DEEP_JOB_TEXT_PAIRS: Array<[string, string]> = [
		['Инструмент долгого выполнения', 'Long-running tool'],
		['Долгое выполнение инструмента', 'Long-running tool'],
		['Задача поставлена в очередь.', 'Task queued.'],
		['Выполняется обработка.', 'Processing in progress.'],
		['Останавливается выполнение.', 'Stopping execution.'],
		['Выполнение завершено.', 'Execution completed.'],
		['Выполнение завершилось с ошибкой.', 'Execution failed.'],
		['Выполнение отменено.', 'Execution cancelled.'],
		['Индексация', 'Indexing'],
		['Анализ', 'Analysis'],
		['Завершение', 'Completion'],
		['Шаг завершён.', 'Step completed.'],
		['Подготавливаем фрагменты документа.', 'Preparing document fragments.'],
		['Собираем итоговый вывод.', 'Compiling the final summary.'],
		['Итог сохранён отдельным ответом ассистента.', 'Result saved in a separate assistant response.'],
		['Журнал выполнения', 'Execution log'],
		['Обновлено', 'Updated'],
		['Ошибка', 'Error'],
		['В очереди', 'Queued'],
		['Выполняется', 'Running'],
		['Завершено', 'Completed'],
		['С ошибкой', 'Failed'],
		['Отменено', 'Cancelled'],
		['Останавливается...', 'Stopping...'],
		['deep-job выполняется.', 'Deep job running.'],
		['deep-job готовится к отмене.', 'Deep job preparing to cancel.'],
		['deep-job завершён.', 'Deep job completed.'],
		['deep-job завершён со статусом failed.', 'Deep job failed.'],
		['deep-job отменён.', 'Deep job cancelled.']
	];

	const localizeDeepJobText = (value: string | null | undefined): string => {
		const text = String(value ?? '').trim();
		if (text === '') {
			return '';
		}

		const locale = getDisplayLocale();
		if (text === 'Deep job' || text === 'Long-running tool') {
			return locale === 'ru' ? 'Инструмент долгого выполнения' : 'Long-running tool';
		}
		if (
			text === 'Глубокая задача' ||
			text === 'Долгое выполнение инструмента' ||
			text === 'Инструмент долгого выполнения'
		) {
			return locale === 'ru' ? 'Инструмент долгого выполнения' : 'Long-running tool';
		}
		for (const [ru, en] of DEEP_JOB_TEXT_PAIRS) {
			if (locale === 'ru' && text === en) {
				return ru;
			}
			if (locale === 'en' && text === ru) {
				return en;
			}
		}

		if (locale === 'en' && text.startsWith('Индексирование ')) {
			return `Indexing ${text.slice('Индексирование '.length)}`;
		}
		if (locale === 'ru' && text.startsWith('Indexing ')) {
			return `Индексирование ${text.slice('Indexing '.length)}`;
		}

		return text;
	};

	const localizeLegacyToolLabel = (value: string | null | undefined): string => {
		const text = String(value ?? '').trim();
		if (text === '') {
			return '';
		}

		const locale = getDisplayLocale();
		for (const [ru, en] of LEGACY_TOOL_LABEL_TEXT_PAIRS) {
			if (locale === 'ru' && text === en) {
				return ru;
			}
			if (locale === 'en' && text === ru) {
				return en;
			}
		}

		return text;
	};

	const getLocalizedUiLabel = (ru: string, en: string) =>
		getDisplayLocale() === 'ru' ? ru : en;

	const translate = (key: string, fallback: string) => {
		const translator = $i18n?.t;
		return typeof translator === 'function' ? translator(key) : fallback;
	};

	const getStateLabel = (state: DeepJobState) => {
		switch (state) {
			case 'queued':
				return localizeDeepJobText(translate('Queued', 'Queued'));
			case 'running':
				return localizeDeepJobText(translate('Running', 'Running'));
			case 'completed':
				return localizeDeepJobText(translate('Completed', 'Completed'));
			case 'failed':
				return localizeDeepJobText(translate('Failed', 'Failed'));
			case 'cancelled':
				return localizeDeepJobText(translate('Cancelled', 'Cancelled'));
			default:
				return state;
		}
	};

	const getProgressPercent = (progress: DeepJobProgress | null) => {
		if (!progress || progress.current === null || progress.total === null || progress.total <= 0) {
			return null;
		}

		return Math.min(100, Math.max(0, (progress.current / progress.total) * 100));
	};

	const getProgressLabel = (progress: DeepJobProgress | null) => {
		if (!progress) {
			return '';
		}

		const values = [progress.current, progress.total].filter((value) => value !== null);
		let label = values.length > 0 ? values.join('/') : '';

		if (progress.unit) {
			label = label ? `${label} ${progress.unit}` : progress.unit;
		}

		return label;
	};

	const getErrorText = (error: DeepJobSnapshot['error']) => {
		if (!error) {
			return '';
		}

		if (typeof error === 'string') {
			return error;
		}

		if (typeof error === 'object') {
			for (const key of ['detail', 'message', 'error']) {
				const value = error[key];
				if (typeof value === 'string' && value.trim() !== '') {
					return value;
				}
			}
		}

		return '';
	};

	const formatTimestamp = (value: string | null) => {
		if (!value) {
			return '';
		}

		const timestamp = new Date(value);
		if (Number.isNaN(timestamp.getTime())) {
			return '';
		}

		return timestamp.toLocaleTimeString([], {
			hour: '2-digit',
			minute: '2-digit'
		});
	};

	onMount(() => {
		deepJobStore.start();

		return () => {
			deepJobStore.destroy();
		};
	});

	$: snapshot = $deepJobStore ?? initialSnapshot;
	$: displayTitle = getCanonicalLongRunningToolLabel();
	$: displayState = snapshot?.state ?? initialState;
	$: displayStateLabel =
		snapshot?.cancel_requested && !isTerminalState(displayState)
			? localizeDeepJobText(translate('Stopping...', 'Stopping...'))
			: getStateLabel(displayState);
	$: displayStateClassName = STATE_CLASSNAMES[displayState] ?? STATE_CLASSNAMES.queued;
	$: displayToolLabel = localizeLegacyToolLabel(snapshot?.tool_label || toolLabel || '');
	$: displaySummary = localizeDeepJobText(snapshot?.summary || initialSummary || title);
	$: showSummary =
		displaySummary !== '' && displaySummary !== displayTitle && displaySummary !== displayToolLabel;
	$: progressLabel = getProgressLabel(snapshot?.progress ?? null);
	$: progressPercent = getProgressPercent(snapshot?.progress ?? null);
	$: errorText = getErrorText(snapshot?.error ?? null);
	$: updatedLabel = formatTimestamp(snapshot?.updated_at ?? null);
	$: steps = snapshot?.steps ?? [];
	$: currentStep = steps.length > 0 ? steps[steps.length - 1] : null;
	$: showCurrentStepCard =
		currentStep !== null &&
		(
			(currentStep.text || '') !== displaySummary ||
			(currentStep.phase || '') !== (snapshot?.phase || '')
		);
	$: completedStepLabels = steps
		.slice(0, -1)
		.map((step) => localizeDeepJobText(`${step.phase || step.text || ''}`.trim()))
		.filter((label, index, labels) => label !== '' && labels.indexOf(label) === index)
		.slice(-4);
</script>

<div
	class="my-2 overflow-hidden rounded-2xl border border-gray-200/80 bg-gray-50/80 text-sm shadow-sm dark:border-gray-800 dark:bg-gray-900/60"
>
	<div class="flex flex-col gap-3 p-4">
		<div class="flex flex-wrap items-center gap-2">
			<div class="min-w-0 flex-1 text-sm font-medium text-gray-900 dark:text-gray-100">{displayTitle}</div>
			<div
				class={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${displayStateClassName}`}
			>
				{displayStateLabel}
			</div>
		</div>

		{#if displayToolLabel}
			<div class="text-sm font-medium text-gray-800 dark:text-gray-100">
				{displayToolLabel}
			</div>
		{/if}

		{#if snapshot?.phase}
			<div class="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
				{localizeDeepJobText(snapshot.phase)}
			</div>
		{/if}

		{#if showSummary}
			<div class="text-sm text-gray-700 dark:text-gray-200">{displaySummary}</div>
		{/if}

		{#if showCurrentStepCard}
			<div class="rounded-xl border border-blue-200/80 bg-white/80 px-3 py-2 dark:border-blue-900/60 dark:bg-gray-950/40">
				{#if currentStep?.phase}
					<div class="text-[11px] font-medium uppercase tracking-wide text-blue-700 dark:text-blue-300">
						{localizeDeepJobText(currentStep.phase)}
					</div>
				{/if}
				<div class="mt-1 text-sm text-gray-800 dark:text-gray-100">
					{localizeDeepJobText(currentStep?.text)}
				</div>
			</div>
		{/if}

		{#if completedStepLabels.length > 0}
			<div class="flex flex-wrap gap-2">
				{#each completedStepLabels as stepLabel}
					<div class="rounded-full border border-gray-200 bg-white/80 px-2 py-0.5 text-[11px] text-gray-600 dark:border-gray-700 dark:bg-gray-950/40 dark:text-gray-300">
						{stepLabel}
					</div>
				{/each}
			</div>
		{/if}

		{#if progressLabel || updatedLabel}
			<div class="space-y-1.5">
				<div class="flex flex-wrap items-center justify-between gap-2 text-[11px] text-gray-500 dark:text-gray-400">
					<div>{progressLabel}</div>
					{#if updatedLabel}
						<div>{localizeDeepJobText(translate('Updated', 'Updated'))} {updatedLabel}</div>
					{/if}
				</div>

				{#if progressPercent !== null}
					<div class="h-1.5 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-800">
						<div
							class="h-full rounded-full bg-blue-500 transition-[width] duration-300 dark:bg-blue-400"
							style={`width: ${progressPercent}%`}
						></div>
					</div>
				{/if}
			</div>
		{/if}

		{#if errorText}
			<div class="rounded-xl border border-red-200 bg-red-50 px-3 py-2 dark:border-red-900/70 dark:bg-red-950/40">
				<div class="text-xs font-medium uppercase tracking-wide text-red-700 dark:text-red-300">
					{localizeDeepJobText(translate('Error', 'Error'))}
				</div>
				<div class="mt-1 text-sm text-red-700 dark:text-red-200">{errorText}</div>
			</div>
		{/if}

		{#if snapshot?.result_message_id}
			<div class="text-xs text-gray-500 dark:text-gray-400">
				{localizeDeepJobText('Result saved in a separate assistant response.')}
			</div>
		{/if}

		{#if steps.length > 0}
			<div class="border-t border-gray-200/80 pt-3 dark:border-gray-800">
				<button
					class="flex w-full items-center justify-between gap-3 text-left text-xs font-medium uppercase tracking-wide text-gray-600 transition hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
					on:click={() => {
						expanded = !expanded;
					}}
				>
					<span>{localizeDeepJobText('Execution log')}</span>
					<svg
						class={`size-4 transition-transform ${expanded ? 'rotate-180' : ''}`}
						viewBox="0 0 20 20"
						fill="currentColor"
						aria-hidden="true"
					>
						<path
							fill-rule="evenodd"
							d="M5.22 8.22a.75.75 0 0 1 1.06 0L10 11.94l3.72-3.72a.75.75 0 1 1 1.06 1.06l-4.25 4.25a.75.75 0 0 1-1.06 0L5.22 9.28a.75.75 0 0 1 0-1.06Z"
							clip-rule="evenodd"
						/>
					</svg>
				</button>

				{#if expanded}
					<div class="mt-3 space-y-2">
						{#each steps as step, stepIdx (`${step.ts ?? 'step'}-${stepIdx}`)}
							<div class="flex items-start gap-3 rounded-xl bg-white/70 px-3 py-2 dark:bg-gray-950/40">
								<div class={`mt-1 size-1.5 rounded-full ${STEP_LEVEL_CLASSNAMES[step.level] ?? STEP_LEVEL_CLASSNAMES.info}`}></div>
								<div class="min-w-0 flex-1">
									<div class="text-sm text-gray-800 dark:text-gray-100">
										{localizeDeepJobText(step.text)}
									</div>
									<div class="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-gray-500 dark:text-gray-400">
										{#if step.phase}
											<span>{localizeDeepJobText(step.phase)}</span>
										{/if}
										{#if formatTimestamp(step.ts)}
											<span>{formatTimestamp(step.ts)}</span>
										{/if}
									</div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>
