# ADR 0005: ChatPage god file 拆分策略

Date: 2026-07-18
Status: accepted

## Context

`client/desktop/src/renderer/src/pages/ChatPage.tsx` 在 P6 之前是 2358 行的 god file：主组件、子组件、纯函数、文件 helper 全部混在一起。直接重写主组件风险太高（hooks/state/useEffect 耦合），但纯函数和无状态子组件是低风险拆分对象，可以独立完成。

## Decision

按"低垂果实优先、主组件保留"的原则拆分：

1. 抽出到 `pages/chatPage/` 子目录：
   - `errorGuards.ts`：错误类型判断（`isAbortError` 等 3 个）。
   - `fileRefHelpers.ts`：文件路径相关纯函数（10 个）。
   - `toolEventHelpers.tsx`：tool event 纯函数 + 无状态子组件（`ToolEventBody`、`WorkIntentBlock`）。
   - `eventCards.tsx`：`JobEventCard` / `PlanEventCard` / `ToolEventCard` 三个无状态卡片组件。
   - `runtimeHelpers.ts`：runtime 还原 / job 合并 / ToolEvent 转换等 6 个纯函数。
2. ChatPage 主组件（含 hooks、state、useEffect、JSX）保留在 `ChatPage.tsx`，本次不动。
3. `GOD_FILE_LINE_BASELINE` 守门：ChatPage.tsx 行数超 1854 即测试失败。
4. 后续若要拆主组件，必须按 custom hook 边界（如 `useChatStreaming`、`useFileAttachment`、`useJobRuntime`）单独提 ADR，不允许在 PR 里顺手拆。

## Consequences

- ChatPage.tsx 2358 → 1854 行（-21%），且新代码不能再往主组件里堆纯函数。
- 纯函数和子组件可以在其他页面复用（如 `eventCards` 已被 `WorkspaceContextPanel` 邻近逻辑引用）。
- 主组件仍是 1780 行，但风险被隔离：本次拆分 TS 编译 0 错误、541 tests passed 无回归。
- 后续主组件 hooks 提取需要专门设计，不能靠"再加一个 helper"敷衍。

## Non-goals

- 不在本次提取 custom hooks（`useChatStreaming` 等）。
- 不在本次拆分其他 page 文件（`SoulPage.tsx` 等）。
- 不在本次引入 React.memo / useMemo 性能优化。
