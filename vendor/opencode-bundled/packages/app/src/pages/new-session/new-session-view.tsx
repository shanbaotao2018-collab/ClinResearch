import { useDialog } from "@opencode-ai/ui/context/dialog"
import { Tooltip } from "@opencode-ai/ui/tooltip"
import { Icon as IconV2 } from "@opencode-ai/ui/v2/icon"
import { TooltipV2 } from "@opencode-ai/ui/v2/tooltip-v2"
import { For, Show, createMemo, createSignal, type Accessor } from "solid-js"
import { createStore } from "solid-js/store"
import { Portal } from "solid-js/web"
import createPresence from "solid-presence"
import { BrandMark } from "@/components/brand-mark"
import { PromptInputV2Composer } from "@/components/prompt-input-v2"
import { PromptGitStatus, PromptWorkspaceSelector } from "@/components/prompt-workspace-selector"
import {
  PromptProjectAddButton,
  PromptProjectSelector,
  type PromptProjectController,
} from "@/components/prompt-project-selector"
import { StatusPopoverV2 } from "@/components/status-popover"
import { useLanguage } from "@/context/language"
import { useLocal } from "@/context/local"
import { useSDK } from "@/context/sdk"
import { useServerSync } from "@/context/server-sync"
import { useProviders } from "@/hooks/use-providers"
import { NEW_SESSION_CONTENT_WIDTH } from "@/pages/session/new-session-layout"
import { Persist, persisted } from "@/utils/persist"
import type { NewSessionDraftController } from "./new-session-draft-controller"
import type { NewSessionWorkspaceController } from "./new-session-workspace-controller"

const providerTipDismissalDuration = 30 * 24 * 60 * 60 * 1000

export function NewSessionView(props: {
  input: NewSessionDraftController["input"]
  project: PromptProjectController
  workspace: NewSessionWorkspaceController
}) {
  const local = useLocal()

  const capabilities = [
    {
      agent: "study-design",
      title: "研究设计",
      description: "把临床想法整理成研究问题、PICO、纳排标准、结局与样本量假设。",
    },
    {
      agent: "literature-review",
      title: "文献检索与综述",
      description: "生成检索式、检索真实文献、去重并辅助完成标题摘要筛选。",
    },
    {
      agent: "evidence-extraction",
      title: "多源证据抽取分析",
      description: "基于已纳入文献提取研究特征、结局数据与质量评价信息。",
    },
    {
      agent: "research-writing",
      title: "科研写作",
      description: "在有来源依据的前提下，生成研究方案、方法学与综述写作初稿。",
    },
  ] as const

  const selectCapability = (capability: (typeof capabilities)[number]) => {
    local.agent.set(capability.agent)
    props.input.restoreFocus()
  }

  return (
    <div class="@container relative flex flex-col min-h-0 h-full flex-1">
      <div
        data-component="session-new-design"
        class="relative flex-1 min-h-0 overflow-hidden rounded-[10px] bg-v2-background-bg-deep"
      >
        <div class="absolute inset-x-0 top-[8%] bottom-8 flex justify-center overflow-y-auto px-6 py-6">
          <div class={`${NEW_SESSION_CONTENT_WIDTH} flex min-h-full flex-col justify-center`}>
            <div class="flex flex-col gap-5">
              <div class="-translate-y-11">
                <section class="flex -translate-y-3 justify-center px-2 pb-5 pt-3">
                  <div class="flex items-center gap-3">
                    <BrandMark class="size-12 rounded-2xl" />
                    <div class="text-[30px] font-semibold tracking-[-0.045em] text-v2-text-text-base">临床科研智能体工作台</div>
                  </div>
                </section>

                <section class="grid grid-cols-1 gap-3 sm:grid-cols-2" aria-label="科研能力入口">
                  <For each={capabilities}>
                    {(capability) => (
                      <button
                        type="button"
                        class="group min-h-[96px] rounded-[10px] border border-[#E5E7EB] bg-[#F8FAFC] px-4 py-3 text-left transition-colors hover:border-[#93C5FD] hover:bg-[#F5F9FF] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0b67a3]/40"
                        onClick={() => selectCapability(capability)}
                      >
                        <div class="mb-2 flex items-center justify-between gap-3">
                          <div class="text-[15px] font-medium text-v2-text-text-base">{capability.title}</div>
                          <span class="shrink-0 text-[11px] text-v2-text-text-faint transition-colors group-hover:text-[#0b67a3]">开始任务 →</span>
                        </div>
                        <p class="line-clamp-2 text-[12px] leading-[18px] text-v2-text-text-muted">{capability.description}</p>
                      </button>
                    )}
                  </For>
                </section>
              </div>

              <PromptInputV2Composer
                controller={props.input}
                placeholder="我想研究“血浆蛋白质组学和糖尿病或代谢性疾病的关联”，请帮我完成研究设计。"
                class="-mt-10 [&_[data-component=prompt-input-v2]]:min-h-[118px] [&_[data-component=prompt-input-v2]]:border [&_[data-component=prompt-input-v2]]:border-[#0b67a3]/20 [&_[data-component=prompt-input-v2]]:shadow-[0_14px_32px_rgba(11,103,163,0.14)] [&_[data-component=prompt-input-v2]]:focus-within:border-[#0b67a3]/55 [&_[data-component=prompt-input]]:min-h-[78px]"
              />
              <Show when={props.project.empty()}>
                <PromptProjectAddButton controller={props.project} />
              </Show>
              <Show when={props.project.selected()}>
                <div class="flex min-h-7 min-w-0 flex-col items-center justify-center gap-0 text-v2-text-text-faint sm:flex-row">
                  <PromptProjectSelector controller={props.project} placement="bottom" />
                  <Show
                    when={props.workspace.bar.visible()}
                    fallback={
                      <PromptGitStatus branch={props.workspace.bar.branch()} noGit={!props.workspace.project.git()} />
                    }
                  >
                    <PromptWorkspaceSelector
                      value={props.workspace.selection.value()}
                      projectRoot={props.workspace.project.root()}
                      workspaces={props.workspace.project.workspaces()}
                      branch={props.workspace.bar.branch()}
                      onChange={props.workspace.selection.set}
                      onDone={props.input.restoreFocus}
                    />
                  </Show>
                </div>
              </Show>
            </div>
          </div>
        </div>
        <ProviderTip />
      </div>
    </div>
  )
}

export function NewSessionStatus(props: { mount: Accessor<HTMLElement | null>; visible: Accessor<boolean> }) {
  const language = useLanguage()

  return (
    <Show when={props.mount()} keyed>
      {(mount) => (
        <Portal mount={mount}>
          <Show when={props.visible()}>
            <Tooltip placement="bottom" value={language.t("status.popover.trigger")}>
              <StatusPopoverV2 />
            </Tooltip>
          </Show>
        </Portal>
      )}
    </Show>
  )
}

function ProviderTip() {
  const language = useLanguage()
  const dialog = useDialog()
  const sdk = useSDK()
  const serverSync = useServerSync()
  const providers = useProviders(() => sdk().directory)
  const [persistedState, setPersistedState, , persistedReady] = persisted(
    Persist.global("new-session.provider-tip"),
    createStore({ dismissedAt: 0 }),
  )
  const visible = createMemo(
    () =>
      serverSync().child(sdk().directory)[0].provider_ready &&
      persistedReady() &&
      providers.paid().length === 0 &&
      Date.now() - persistedState.dismissedAt >= providerTipDismissalDuration,
  )
  const [ref, setRef] = createSignal<HTMLDivElement>()
  const presence = createPresence({
    show: visible,
    element: () => ref() ?? null,
  })
  const openProviders = () => {
    void import("@/components/dialog-connect-provider").then(({ DialogConnectProvider }) => {
      void dialog.show(() => <DialogConnectProvider directory={() => sdk().directory} />)
    })
  }

  return (
    <Show when={presence.present()}>
      <div class="pointer-events-none absolute inset-x-0 bottom-4 flex justify-center px-10">
        <div
          ref={setRef}
          data-component="provider-tip"
          data-visible={visible()}
          class="group/provider-tip pointer-events-auto relative flex h-6 max-w-full items-center transition-[opacity,transform] duration-[250ms] ease-[cubic-bezier(0.215,0.61,0.355,1)] motion-reduce:transition-none"
          classList={{ "data-[visible=false]:animate-out fade-out slide-out-to-bottom-4": true }}
        >
          <button
            type="button"
            class="flex h-6 min-w-0 items-center rounded-[4px] pl-1.5 text-[13px] leading-none tracking-[-0.04px] text-v2-text-text-faint transition-[background-color,color] duration-150 ease-in-out hover:bg-v2-overlay-simple-overlay-hover hover:text-v2-text-text-muted focus-visible:bg-v2-overlay-simple-overlay-hover focus-visible:text-v2-text-text-muted focus-visible:outline-none"
            onClick={openProviders}
          >
            <span class="truncate">{language.t("home.providerTip")}</span>
            <span class="flex size-6 shrink-0 items-center justify-center" aria-hidden="true">
              <IconV2 name="chevron-down" size="small" class="-rotate-90" />
            </span>
          </button>
          <TooltipV2
            class="hover-reveal absolute left-full top-0 flex h-6 w-7 items-center justify-end delay-0 duration-0 group-hover/provider-tip:delay-[250ms] group-hover/provider-tip:duration-150 group-hover/provider-tip:opacity-100 focus-within:delay-0 focus-within:duration-0 focus-within:opacity-100"
            placement="top"
            openDelay={1000}
            value={language.t("common.dismiss")}
          >
            <button
              type="button"
              class="flex size-6 items-center justify-center rounded-[4px] text-v2-icon-icon-muted transition-[background-color,color] duration-150 ease-in-out hover:bg-v2-overlay-simple-overlay-hover hover:text-v2-icon-icon-base focus-visible:bg-v2-overlay-simple-overlay-hover focus-visible:text-v2-icon-icon-base focus-visible:outline-none"
              aria-label={language.t("common.dismiss")}
              onClick={() => setPersistedState("dismissedAt", Date.now())}
            >
              <IconV2 name="xmark-small" />
            </button>
          </TooltipV2>
        </div>
      </div>
    </Show>
  )
}
