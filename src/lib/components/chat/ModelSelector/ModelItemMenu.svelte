<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { goto } from '$app/navigation';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Pin from '$lib/components/icons/Pin.svelte';
	import PinSlash from '$lib/components/icons/PinSlash.svelte';
	import Link from '$lib/components/icons/Link.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
	import { config, settings, user } from '$lib/stores';
	import GlobeAlt from '$lib/components/icons/GlobeAlt.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';

	const i18n: Writable<i18nType> = getContext('i18n');

	export let show = false;
	export let model: any;

	export let pinModelHandler: (modelId: string) => void = () => {};
	export let copyLinkHandler: Function = () => {};
	export let deleteModelHandler: Function = () => {};

	export let onClose: Function = () => {};
	export let unregisterRuntimeRegistrationHandler: Function = () => {};

	$: runtimeRegistration =
		model?.info?.meta?.runtime_registration &&
		typeof model.info.meta.runtime_registration === 'object' &&
		!Array.isArray(model.info.meta.runtime_registration)
			? model.info.meta.runtime_registration
			: null;
	$: runtimeCatalogOrigin =
		model?.info?.meta?.catalog_origin ?? runtimeRegistration?.catalog_origin ?? null;
	$: runtimeManaged =
		Boolean($config?.features?.enable_agent_navigator_runtime_models) &&
		runtimeCatalogOrigin === 'dynamic';
	$: usesWorkspaceEditor = runtimeManaged || model?.preset || model?.info?.base_model_id;
	$: canEdit = runtimeManaged
		? $user?.role === 'admin' || model?.info?.user_id === $user?.id
		: usesWorkspaceEditor
			? model?.info?.user_id === $user?.id
			: $user?.role === 'admin';
	$: pinnedModels = Array.isArray($settings?.pinnedModels)
		? ($settings.pinnedModels as string[])
		: [];
</script>

<Dropdown
	bind:show
	align="end"
	sideOffset={-2}
	onOpenChange={(state) => {
		if (state === false) {
			onClose();
		}
	}}
>
	<Tooltip
		content={$i18n.t('More')}
		className={($settings?.highContrastMode ?? false)
			? ''
			: 'group-hover/item:opacity-100 opacity-0'}
	>
		<slot />
	</Tooltip>

	<div slot="content">
		<div
			class="min-w-[210px] text-sm rounded-2xl p-1 z-[9999999] bg-white dark:bg-gray-850 dark:text-white shadow-lg border border-gray-100 dark:border-gray-800"
		>
			{#if canEdit}
				<button
					type="button"
					class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2"
					on:click={(e) => {
						e.stopPropagation();
						e.preventDefault();

						goto(
							usesWorkspaceEditor
								? `/workspace/models/edit?id=${encodeURIComponent(model?.id ?? '')}`
								: `/admin/settings/models?id=${encodeURIComponent(model?.id ?? '')}`
						);
						show = false;
					}}
				>
					<Pencil className="size-4" />

					<div class="flex items-center">{runtimeManaged ? $i18n.t('Configure model') : $i18n.t('Edit')}</div>
				</button>

				{#if $user?.role === 'admin' && model?.owned_by === 'ollama'}
					<button
						type="button"
						class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2"
						on:click={(e) => {
							e.stopPropagation();
							e.preventDefault();

							deleteModelHandler(model);
							show = false;
						}}
					>
						<GarbageBin />

						<div class="flex items-center">{$i18n.t('Delete')}</div>
					</button>
				{/if}

				{#if $user?.role === 'admin' && runtimeManaged}
					<button
						type="button"
						class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2 text-rose-600 dark:text-rose-400"
						on:click={(e) => {
							e.stopPropagation();
							e.preventDefault();

							unregisterRuntimeRegistrationHandler(model);
							show = false;
						}}
					>
						<GarbageBin />

						<div class="flex items-center">{$i18n.t('Delete runtime registration')}</div>
					</button>

					<hr class="border-gray-50 dark:border-gray-800/30 my-1" />
				{:else}
					<hr class="border-gray-50 dark:border-gray-800/30 my-1" />
				{/if}
			{/if}

			<button
				type="button"
				aria-pressed={pinnedModels.includes(model?.id)}
				class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2"
				on:click={(e) => {
					e.stopPropagation();
					e.preventDefault();

					pinModelHandler(model?.id);
					show = false;
				}}
			>
				{#if pinnedModels.includes(model?.id)}
					<PinSlash />
				{:else}
					<Pin />
				{/if}

				<div class="flex items-center">
					{#if pinnedModels.includes(model?.id)}
						{$i18n.t('Hide from Sidebar')}
					{:else}
						{$i18n.t('Keep in Sidebar')}
					{/if}
				</div>
			</button>

			<button
				type="button"
				class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2"
				on:click={(e) => {
					e.stopPropagation();
					e.preventDefault();

					copyLinkHandler();
					show = false;
				}}
			>
				<Link />

				<div class="flex items-center">{$i18n.t('Copy Link')}</div>
			</button>

			{#if $config?.features.enable_community_sharing}
				<hr class="border-gray-50 dark:border-gray-800/30 my-1" />

				<button
					type="button"
					class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2"
					on:click={(e) => {
						e.stopPropagation();
						e.preventDefault();

						window.open(
							`https://openwebui.com/models?q=${encodeURIComponent(model?.id ?? '')}`,
							'_blank'
						);
						show = false;
					}}
				>
					<GlobeAlt className="size-4" />

					<div class="flex items-center">{$i18n.t('Community Reviews')}</div>
				</button>
			{/if}
		</div>
	</div>
</Dropdown>
