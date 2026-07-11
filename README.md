# ChatGPT–Codex Collaboration

一套 **macOS-first、以 Codex 原生 `/goal` 為上層控制權**的雙代理開發與驗收流程。

ChatGPT 負責主要程式實作；Codex 負責拆出有限 task、掌握 PRD／SDD／spec、驗證 Git candidate、執行測試、退回修正，並持續推進完整目標。

GitHub remote branch 與 commit SHA 是正式交接邊界。

> 目前支援 macOS 13 Ventura 以上。Linux、Windows 與 WSL 暫不支援。

---

## 設計目標

這個 Skill 的成本策略是：

```text
大量產碼、修改、重工
→ 交給 ChatGPT 訂閱方案中的高階模型

少量但必要的規格判斷、測試與驗收
→ 交給 Codex
```

同時避免：

- ChatGPT 自己寫、自己宣布驗收通過
- ChatGPT 回覆完成，卻沒有 candidate commit
- ChatGPT 沒有 shell，Codex 卻要求它先跑完本機測試
- Codex 等待 ChatGPT 時反覆產生 `/goal` continuation turns
- 長時間 shell `await` 被平台每幾分鐘切斷
- task blocker 被誤升級成完整 native goal blocker
- 遠端 branch 根本不存在，ChatGPT connector 無法提交

---

## 角色分工

| 角色 | 職責 |
|---|---|
| **Codex `/goal`** | 保存完整目標與跨 task 連續性 |
| **Codex** | 定義 task、掌握 spec、準備 branch、驗收、退修、判斷 goal 是否完成 |
| **ChatGPT** | 依 profile 實作並建立 candidate commit |
| **GitHub** | 程式碼與交接證據的正式邊界 |
| **launchd supervisor** | 無模型地監控 Git／transport event，事件到達後恢復同一 Codex session |
| **使用者** | 決定未定義的產品行為與明確 goal 變更 |

---

## 核心不變式

1. ChatGPT 不得驗收自己的實作
2. Codex 驗收失敗時，不得偷偷代替 ChatGPT 修正
3. 遠端 commit SHA 不存在，就沒有完成 handoff
4. 測試通過不等於 spec 通過
5. 單一 task 通過不等於完整 `/goal` 完成
6. Task blocked 不等於 native goal blocked
7. 外部等待期間不得產生重複 Codex reasoning turns
8. Goal、task、executor profile、branch、SHA 與驗收證據都必須可恢復

---

## 架構

```text
Native Codex /goal
  │
  ▼
Codex verifier/orchestrator on macOS
  ├─ Mac Doctor
  ├─ Native Goal Gate
  ├─ ChatGPT Capability Handshake
  ├─ Remote Branch Preparation
  ├─ Profile-aware Task Contract
  ├─ Strict Handoff Receipt
  ├─ Task State
  ├─ launchd Event Supervisor
  ├─ app-server goal pause / resume
  ├─ codex exec resume <CODEX_THREAD_ID>
  └─ Local Acceptance
          ▲
          │ remote branch / candidate commit
          ▼
ChatGPT implementer
  ├─ local_full
  └─ github_connector
```

完整設計見 [`docs/architecture.md`](docs/architecture.md)。

---

## 為什麼不用 blocking await

舊流程嘗試讓 Codex turn 長時間阻塞在：

```sh
macos-watcher.sh await ...
```

但實際執行環境可能每數分鐘強制切斷 command。結果變成：

```text
await 被切斷
→ active /goal 再開 continuation turn
→ Codex 再次等待
→ 再被切斷
→ 重複消耗 token 與模型容量
```

新版正式流程改成：

```text
成功派工
→ 暫停同一個 native goal
→ 結束目前 Codex turn
→ launchd 無模型監控 Git 與 transport event
→ 事件到達
→ 恢復同一個 goal
→ codex exec resume 同一個 CODEX_THREAD_ID
→ Codex 驗收或處理 blocker
```

`macos-watcher.sh await` 現在已停用，不能再作為正式流程。

---

## Executor Profiles

正式派工前，ChatGPT 必須回傳 capability handshake。

| Profile | ChatGPT 能力 | ChatGPT 責任 | Codex 責任 |
|---|---|---|---|
| `local_full` | 本機 checkout、shell、commit、push | 實作並跑 focused checks | 重跑並獨立驗收 |
| `github_connector` | GitHub read/write/commit/push，沒有本機 shell | 建立未測試 candidate，測試回 `not_run` | 本機執行全部驗收 |
| `read_only` | 只能讀 | 無法交件 | Task `BLOCKED_CAPABILITY` |
| `none` | 無 repository executor | 無法交件 | Task `BLOCKED_CAPABILITY` |

`github_connector` 沒有 shell 不算 blocker，只要它能在已存在的 remote branch 建立 commit。

詳見 [`docs/capability-handshake.md`](docs/capability-handshake.md)。

---

## Strict Handoff Receipt

ChatGPT 最後必須回傳符合 [`contracts/handoff-receipt.schema.json`](contracts/handoff-receipt.schema.json) 的 JSON receipt。

### Completed

```json
{
  "schema_version": "1.0",
  "task_id": "TASK-001",
  "status": "completed",
  "executor_profile": "github_connector",
  "branch": "chatgpt/TASK-001",
  "base_sha": "0000000000000000000000000000000000000000",
  "commit_sha": "1111111111111111111111111111111111111111",
  "changed_files": ["src/example.ts"],
  "test_results": [
    {"command": "npm test", "status": "not_run", "exit_code": null}
  ],
  "verification_status": "pending_codex_verification",
  "blockers": []
}
```

### Blocked

```json
{
  "schema_version": "1.0",
  "task_id": "TASK-001",
  "status": "blocked",
  "executor_profile": "github_connector",
  "branch": "chatgpt/TASK-001",
  "base_sha": "0000000000000000000000000000000000000000",
  "commit_sha": null,
  "changed_files": [],
  "test_results": [],
  "verification_status": "blocked",
  "blockers": ["GitHub connector cannot create commits"]
}
```

以下不算完成：

```text
tests = not_run
verification_status = pending_codex_verification
blockers = none
commit_sha = missing
```

這會被判定為 `conversation_completed_no_commit`，不是 handoff。

驗證 receipt：

```sh
sh "$SKILL_ROOT/scripts/validate-handoff-receipt.sh" \
  /path/to/receipt.json
```

---

## 支援環境

- macOS 13+
- Apple Silicon 或 Intel
- Python 3.9+
- Git 2.30+
- Xcode Command Line Tools
- Codex CLI，且支援：
  - `codex app-server`
  - `codex exec resume`
  - native `/goal`
- Codex shell 中可取得 `CODEX_THREAD_ID`
- 可讀寫的 GitHub remote
- Codex 本機完整 checkout 與 command execution
- 可操作既有 ChatGPT conversation 的 transport adapter
- ChatGPT 至少具有 `local_full` 或 `github_connector`

---

## 安裝

### 使用者層級

```sh
mkdir -p "$HOME/.agents/skills"
git clone \
  https://github.com/backtrue/chatgpt-codex-collaboration.git \
  "$HOME/.agents/skills/chatgpt-codex-collaboration"
```

更新：

```sh
git -C "$HOME/.agents/skills/chatgpt-codex-collaboration" pull
```

### 專案層級

```sh
mkdir -p .agents/skills
git clone \
  https://github.com/backtrue/chatgpt-codex-collaboration.git \
  .agents/skills/chatgpt-codex-collaboration
```

安裝或更新後，重新載入 Codex session。

---

## 快速開始

### 1. 設定 Skill 路徑

```sh
SKILL_ROOT="$HOME/.agents/skills/chatgpt-codex-collaboration"
```

### 2. 從 Codex shell 執行 Doctor

```sh
sh "$SKILL_ROOT/scripts/macos-doctor.sh" \
  --strict-runtime \
  --repo "$PWD" \
  --remote origin
```

### 3. 啟動 Skill

```text
使用 chatgpt-codex-collaboration，依照目前 PRD、SDD 與 spec，
讓 ChatGPT 分段實作，Codex 獨立驗收與退修，直到完整目標完成。
```

### 4. Capability Handshake

Skill 先確認 ChatGPT 是：

```text
local_full
或
github_connector
```

### 5. 準備遠端 branch

```sh
sh "$SKILL_ROOT/scripts/prepare-handoff-branch.sh" \
  "$PWD" \
  origin \
  chatgpt/TASK-001 \
  <base-sha>
```

### 6. 派工並啟動 event supervisor

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" start \
  TASK-001 \
  chatgpt/TASK-001 \
  <base-sha> \
  --repo "$PWD" \
  --remote origin \
  --dispatch-epoch <unix-epoch>
```

`start` 成功後：

- remote branch 已驗證
- 同一 native goal 暫時 paused
- LaunchAgent 已建立
- wake config 已保存
- 目前 Codex turn 可以結束

不要執行 `await`。

---

## 事件驅動恢復

Supervisor 監看：

- remote branch HEAD
- ChatGPT terminal event JSONL
- observation lease

事件出現後會：

```text
同一 goal → active
同一 CODEX_THREAD_ID → codex exec resume
同一 task → 驗收或 recovery
```

若自動 resume 失敗：

- goal 回到 paused
- 顯示 macOS notification
- 保留 resume log
- 允許重試同一事件

檔案位置：

```text
~/Library/LaunchAgents/com.backtrue.chatgpt-codex.<task-id>.plist
~/.codex/collaboration/tasks/<task-id>.json
~/.codex/collaboration/events/<task-id>.jsonl
~/.codex/collaboration/wakes/<task-id>.json
~/.codex/collaboration/logs/<task-id>.out.log
~/.codex/collaboration/logs/<task-id>.err.log
~/.codex/collaboration/logs/<task-id>.codex-resume.log
```

---

## Transport Events

ChatGPT transport adapter 在 terminal condition 時寫入：

```sh
sh "$SKILL_ROOT/scripts/transport-event.sh" emit \
  TASK-001 conversation_completed_no_commit \
  --source chatgpt-ui \
  --reason "ChatGPT completed without a valid candidate commit"
```

支援事件：

- `implementation_blocked`
- `capability_rejected`
- `conversation_completed_no_commit`
- `conversation_failed`
- `transport_unreachable`
- `mode_drifted`

有效 candidate commit 會由 Git branch movement 直接觸發，不必另寫 UI event。

---

## Codex Acceptance

Candidate 出現後，Codex 執行：

```sh
sh "$SKILL_ROOT/scripts/validate-handoff.sh" \
  <repo-path> \
  <remote> \
  <branch> \
  <base-sha> \
  <candidate-sha> \
  <allowed-path>...
```

並檢查：

- candidate 是目前 remote branch HEAD
- candidate 不等於 base SHA
- changed files 在 allowed scope
- 沒有 secrets、壓縮檔與暫存檔
- focused tests
- typecheck、lint 與 regression suite
- browser behavior（必要時）
- spec 與 goal alignment

`github_connector` 的 `not_run` 是正常輸入，但 Codex 必須本機補跑全部 acceptance。

---

## Native Goal Safety

Task blocker 不得直接變更 native goal 為 blocked。

只有完整 goal blocker：

- 跨至少三個 native goal turns 重複
- 沒有 executor／transport／repair／local verification fallback
- 無法靠使用者或外部狀態變更推進

才可以 `update_goal(status="blocked")`。

External wait 的 temporary pause 只是 transport suspension，必須和 event-driven resume 配對，不能用來代表失敗。

詳見 [`docs/native-goal-safety.md`](docs/native-goal-safety.md)。

---

## 恢復舊版卡死任務

1. 更新 Skill
2. 停止舊 watcher 並恢復同一 goal：

   ```sh
   sh "$SKILL_ROOT/scripts/macos-watcher.sh" stop \
     <task-id> \
     --resume-goal
   ```

3. 執行 capability recovery：

   ```sh
   sh "$SKILL_ROOT/scripts/recover-capability.sh" <task-id>
   ```

4. 重新 handshake
5. 驗證或建立遠端 branch
6. 拒絕沒有 commit SHA 的舊 ChatGPT 回覆
7. 重新派送 strict receipt contract
8. 使用 event-driven `start`

不要建立替代 goal，也不要重新啟動 blocking await。

---

## Repository 結構

```text
.
├── SKILL.md
├── README.md
├── dependencies.yaml
├── agents/openai.yaml
├── config/
│   ├── executor.example.yaml
│   └── capability-handshake.example.json
├── contracts/
│   ├── collaboration.schema.json
│   └── handoff-receipt.schema.json
├── docs/
│   ├── architecture.md
│   ├── capability-handshake.md
│   ├── goal-integration.md
│   ├── native-goal-safety.md
│   └── macos.md
└── scripts/
    ├── codex-goal-control.py
    ├── event-supervisor.py
    ├── macos-doctor.py
    ├── macos-watcher.py
    ├── prepare-handoff-branch.py
    ├── task-state.py
    ├── transport-event.py
    ├── validate-handoff-receipt.py
    ├── validate-handoff.py
    └── wake-codex.py
```

---

## 目前邊界

本 repo 已提供：

- native goal 綁定與 transport suspension
- capability handshake
- remote branch preparation
- strict handoff receipt
- persistent task state
- launchd event supervisor
- Git／transport terminal observation
- automatic same-session `codex exec resume`
- independent Codex acceptance
- recovery rules

仍需要 ChatGPT transport adapter 實際做到：

1. 開啟既有對話
2. 確認 Chat mode
3. 發送並解析 handshake
4. 發送 profile-aware contract
5. 解析 strict handoff receipt
6. 對 invalid／blocked／failed response 寫入 terminal event

目前為 **macOS-first experimental workflow**。先在測試 repository 完整跑通 suspend → Git commit → same-session resume → Codex acceptance，再投入重要專案。
