---
name: chatgpt-codex-collaboration
description: Coordinate a macOS-first two-agent coding workflow in which ChatGPT performs most implementation work through a local executor or GitHub connector, while Codex uses low-cost planning, monitoring, handoff, acceptance, and repair control. Use when ChatGPT should be the primary developer, Codex should minimize model turns, or browser-based ChatGPT handoffs must avoid repeated screenshots, missing commits, false receipts, and goal deadlocks.
---

# ChatGPT-Codex Collaboration

## 設計目的（不可偏離）

本 skill 不是讓 ChatGPT 與 Codex 平等分擔開發，而是進行模型能力與 token 成本分工：
使用高能力、適合複雜理解與實作的 ChatGPT 作為主力開發者，使用低成本 Codex 作為
企劃、監測、交接、驗證與控制者，以較低 Codex token 成本完成可靠開發。

不可偏離原則：

- ChatGPT 優先承擔複雜需求理解、程式修改與實作細節。
- Codex 優先承擔有限工作拆分、規格守門、GitHub 交接、驗證、退回與狀態控制。
- Codex 不應接手 ChatGPT 的主要實作，除非使用者明確改變分工。
- 沒有新證據時，Codex 不得重複截圖、輪詢、重送 repair 或消耗 continuation turn。
- 任何維護修改都必須先確認沒有把 Codex 變成主要實作者或重複觀察者。

## 角色與交接邊界

- Native Codex `/goal`：完整目標與跨回合延續權限。
- ChatGPT：一次只實作一個有限、對齊 goal 的工作。
- Codex：定義工作、守 authoritative spec、驗收 candidate、決定 repair。
- GitHub branch + commit SHA：唯一程式交接證據。
- 使用者：決定 spec 未定義的產品行為與明確 goal 變更。

ChatGPT 不得自行宣告驗收；Codex 不得默默代做交給 ChatGPT 的 repair。沒有遠端
commit SHA 的回覆不是 handoff。

## 只讀這些入口資源

先解析 `SKILL_ROOT` 為本檔案所在的絕對目錄，所有 bundled script 都用絕對路徑執行。

- 流程架構：`docs/architecture.md`
- macOS、LaunchAgent、browser-use：`docs/macos.md`
- native goal 安全：`docs/native-goal-safety.md`
- blocker 去重與 quiescence：`docs/quiescent-blockers.md`
- goal 交接：`docs/goal-integration.md`
- capability handshake：`docs/capability-handshake.md`
- task / handoff 合約：`contracts/collaboration.schema.json`、`contracts/handoff-receipt.schema.json`
- 依賴與 executor profile：`dependencies.yaml`
- browser transport：`scripts/browser-use-transport.sh`
- supervisor：`scripts/macos-watcher.sh`、`scripts/transport-event.sh`
- handoff 驗證：`scripts/validate-handoff.sh`、`scripts/validate-handoff-receipt.sh`
- goal / state：`scripts/codex-goal-control.sh`、`scripts/task-state.sh`

需要細節時才讀對應資源，不要先載入整個 skill package。

## 最小正式流程

### 1. Goal 與環境 gate

1. 呼叫 `get_goal`；保留同一 `goal_id` 與完整 objective。
2. 沒有 goal 或前一 goal 已完成時，依使用者 end state 與 authoritative spec 呼叫 `create_goal`。
3. 不因 task blocker 呼叫 `update_goal(status="blocked")`，不清除、替換或永久 pause goal。
4. macOS 13+、`CODEX_THREAD_ID`、`codex app-server`、`codex exec resume`、完整 local checkout、local acceptance command、`browser-use` 與 Chrome/Chromium CDP 必須先通過 doctor。
5. 詳細安全與 recovery 規則讀 `docs/native-goal-safety.md`。

### 2. Spec、能力與有限工作

1. 讀 repo instructions、PRD/SDD/spec/acceptance 文件。
2. 只選一個有限工作，列出 allowed paths、forbidden changes、acceptance commands。
3. 讓 ChatGPT 先回傳 capability handshake；只能接受 `local_full` 或 `github_connector`。
4. `local_full` 由 ChatGPT 跑 focused checks；`github_connector` 可不跑本機測試，Codex 在本機全部驗收。
5. 用 `contracts/collaboration.schema.json` 建立 task contract，先建立遠端 branch 並記錄 base SHA。

### 3. Browser-use dispatch

正式 web 路徑使用 `scripts/browser-use-transport.sh`，不使用 `computer-use`、
`screencapture` 或 `osascript` 作等待器。

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" start \
  <task-id> <branch> <base-sha> \
  --repo <absolute-repo-path> --remote <remote> \
  --executor-profile <local_full|github_connector> \
  --browser-script "$SKILL_ROOT/scripts/browser-use-transport.py" \
  --conversation-url <approved-chatgpt-url> \
  --prompt-file <absolute-contract-file> \
  --dispatch-id <unique-dispatch-id> \
  --message-fingerprint <sha256-of-prompt>
```

Browser transport 必須：

- 開啟指定既有對話並確認 plain `Chat` mode；遇到 Work/Task/Project/Canvas 立即 emit `mode_drifted`。
- 發送一次 prompt，記錄 dispatch 與 fingerprint；不得重送相同 dispatch。
- 在 Codex turn 結束後於背景以 CDP 讀 DOM 狀態，不呼叫 LLM。
- 看到 remote branch commit、完成回覆、失敗、CDP 失效或 lease expiry 時寫入 terminal event。
- 無法控制瀏覽器時 emit `transport_unreachable`，不可改用重複截圖或重送 prompt。

### 4. Event-driven wait

`macos-watcher.sh start` 會：

1. 確認 remote branch 在 exact base SHA。
2. 暫時 pause 同一 native goal。
3. 啟動 LaunchAgent event supervisor 與 browser-use transport。
4. 立即結束目前 Codex turn；禁止 blocking `await`。

等待期間只由背景程序監控 Git、browser transport event 與 lease。相同 task/fingerprint
只能有一個 wake。沒有新證據時維持 paused，不建立新的 continuation。

### 5. Handoff 與 acceptance

1. branch 變更只是 candidate，不是 acceptance。
2. 先執行 `validate-handoff.sh`，確認 current remote HEAD、base SHA、allowed scope、無 secrets/archives/temporary files。
3. 讀 `handoff-receipt.schema.json`；completed 必須有 40 字元 commit SHA，blocked 必須有明確 blocker。
4. Codex 重新讀 spec、拉回 candidate、跑 focused acceptance、regression、error/boundary/security checks。
5. 只有 `VERIFYING` 可以轉成 `ACCEPTED`；ChatGPT 的測試回報不能取代 Codex 驗收。

### 6. Repair、停止與 goal 延續

驗收失敗時：

1. 轉 `REPAIR_REQUIRED`，保留原始錯誤、spec 行號、預期修正與 scope。
2. 不在本機偷偷修 ChatGPT 的實作；同一對話只送一個 repair contract。
3. 以新 base SHA、全新 dispatch ID、全新 fingerprint 重啟 event-driven wait。
4. 同一 blocker 沒有新證據時使用 quiescence；不要反覆發 status 或 repair。

驗收通過後：停止 LaunchAgent、保存 accepted SHA，再重新審查完整 goal。只有所有 goal
要求都證明完成時才可 `update_goal(status="complete")`；否則保持 active 並選下一個有限工作。

## 不可違反的等待安全規則

- 不使用 `macos-watcher.sh await`。
- 不讓 active goal 在外部 ChatGPT 工作期間持續產生 continuation turns。
- 不把 task-level blocker 說成 complete-goal blocker。
- resume 前建立 in-flight marker；同 fingerprint 只允許一個 resume。
- resume 超過 bounded timeout 時終止、保留 event、pause 同一 goal，等待新證據。
- 不以 deterministic fallback、猜測產品行為或沒有 commit 的 prose 取代證據。

完整狀態機、事件欄位、recovery 與驗收規則只在上方列出的 docs/contracts 中維護。
