# ChatGPT–Codex Collaboration

一套 **macOS-first、以 Codex 原生 `/goal` 為上層控制權**的雙代理開發與驗收流程。

ChatGPT 負責主要程式實作；Codex 負責讀取 PRD／SDD／spec、拆出有限 task、驗收 Git diff、執行測試與退回修正。GitHub branch 是兩者之間正式且可稽核的交接邊界。

> 第一版只支援 macOS 13 Ventura 以上。

---

## 目標

這個 Skill 的成本分工是：

```text
大量產碼、修改與重工
→ ChatGPT

少量規格判斷、測試與驗收
→ Codex
```

同時避免：

- ChatGPT 自己驗收自己的程式。
- Codex 驗收失敗後直接代替 ChatGPT 修正。
- ChatGPT 沒有合法執行環境，Codex 卻無限等待 commit。
- active `/goal` 在等待期間反覆啟動 continuation turn。
- 測試未跑，卻被錯誤當成任務失敗或正式完成。

---

## 角色分工

| 角色 | 職責 |
|---|---|
| **Codex `/goal`** | 保存完整目標並跨 turn 延續工作 |
| **Codex** | 拆 task、掌握 spec、本機跑驗證、驗收與退修 |
| **ChatGPT** | 依 executor profile 實作並提交 candidate commit |
| **GitHub** | 程式碼、branch、commit 與 diff 的正式交接邊界 |
| **使用者** | 裁決未定義產品行為與明確 goal 變更 |

---

## 關鍵修正：先確認 ChatGPT 能做什麼

能開啟 ChatGPT 對話，不代表 ChatGPT 一定有：

- 本機 repository checkout；
- shell；
- npm／pytest／build tool；
- GitHub 外部網路；
- branch commit 權限。

因此 Skill 現在會在正式派工前執行 **Capability Handshake**。

```text
Goal Gate
→ 建立 task state
→ CAPABILITY_CHECK
→ ChatGPT 回報真實 executor profile
→ 依 profile 產生不同 Task Contract
→ 通過後才啟動 watcher
```

### Executor profiles

| Profile | ChatGPT 能力 | 任務策略 |
|---|---|---|
| `local_full` | 本機 checkout、shell、測試、commit、push | ChatGPT 先跑 focused checks，再提交；Codex仍獨立重跑 |
| `github_connector` | GitHub connector 可讀寫並建立 branch commit，無本機 shell | 允許未測試 candidate；ChatGPT 回報 `not_run`，Codex 本機跑全部驗證 |
| `read_only` | 只能讀，不能提交 | `BLOCKED_CAPABILITY`，不啟動 watcher |
| `none` | 無可用 repository executor | `BLOCKED_CAPABILITY`，不啟動 watcher |

完整規格見 [`docs/capability-handshake.md`](docs/capability-handshake.md)。

---

## GitHub Connector 模式

這是這次 bug 的主要修正。

當 ChatGPT 只有 GitHub connector 時，Task Contract 會明確寫：

```text
Executor profile: github_connector
Implementation validation policy: deferred_to_codex
Candidate commit without tests: true
```

ChatGPT 不需要本機 clone，也不需要 shell。它應：

1. 透過 GitHub connector 讀取 assigned branch。
2. 修改 allowed paths。
3. 建立 candidate commit。
4. 將無法執行的 commands 回報為 `status=not_run`。
5. 回傳 `verification_status=pending_codex_verification`。

之後 Codex 在本機執行：

- focused tests；
- typecheck；
- lint；
- required regression tests；
- browser checks；
- spec acceptance。

**未測試 candidate 可以存在；未經 Codex 驗收的 candidate 不可以 merge。**

---

## Blocker-aware watcher

### 原本的死鎖

```text
ChatGPT：沒有 checkout／shell，不可能產生合法 commit
Codex：等待 branch commit
ChatGPT：不會有 commit
Codex：持續等待
```

### 現在的流程

ChatGPT transport adapter 會將 terminal condition 寫入本機事件檔：

```text
~/.codex/collaboration/events/<task-id>.jsonl
```

例如：

```sh
sh "$SKILL_ROOT/scripts/transport-event.sh" emit \
  TASK-001 implementation_blocked \
  --source chatgpt-ui \
  --code NO_LOCAL_EXECUTOR \
  --reason "No local checkout or shell is available"
```

`macos-watcher.sh await` 同時監聽：

- Git branch candidate；
- ChatGPT terminal blocker。

下列事件會立即喚醒 Codex並停止 Git watcher：

- `implementation_blocked`
- `conversation_completed_no_commit`
- `conversation_failed`
- `transport_unreachable`
- `mode_drifted`

不會再等到兩小時 lease expiry 才發現不可能有 commit。

---

## 低 Token 等待

背景 Git watcher 不呼叫 LLM：

- 初始 polling：60 秒；
- 連續無變化後漸進退避；
- 最大 polling：300 秒；
- 只記錄狀態改變。

啟動：

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" start \
  TASK-001 chatgpt/TASK-001 <base-sha> \
  --repo "$PWD" \
  --remote origin \
  --dispatch-epoch <unix-epoch>
```

接著阻塞目前 Codex turn：

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" await \
  TASK-001 --timeout-seconds 7500
```

`await` 只讀本機 logs 與 transport events，不呼叫模型，也不查 GitHub。保持目前 Codex turn active，可避免 `/goal` 因 thread idle 而反覆開新 turn。

---

## 架構

```text
Native Codex /goal
  │
  ▼
Codex verifier on macOS
  ├─ Mac Doctor
  ├─ Goal Gate
  ├─ Capability Handshake
  ├─ Profile-aware Task Contract
  ├─ local task state
  ├─ launchd Git watcher
  ├─ local transport terminal events
  ├─ blocking await
  └─ local acceptance runner
          ▲
          │ GitHub branch / commit
          ▼
ChatGPT implementer
  ├─ local_full
  └─ github_connector
```

詳見 [`docs/architecture.md`](docs/architecture.md)。

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

設定 Skill 路徑：

```sh
SKILL_ROOT="$HOME/.agents/skills/chatgpt-codex-collaboration"
```

### 專案層級

```sh
mkdir -p .agents/skills
git clone \
  https://github.com/backtrue/chatgpt-codex-collaboration.git \
  .agents/skills/chatgpt-codex-collaboration
```

安裝後重新載入 Codex session。

---

## Mac Doctor

```sh
sh "$SKILL_ROOT/scripts/macos-doctor.sh" \
  --repo "$PWD" \
  --remote origin
```

要求：

- macOS 13+
- Python 3.9+
- Git 2.30+
- Xcode Command Line Tools
- Codex CLI with native Goal tools
- launchd
- ChatGPT conversation transport
- Codex 本機 repository checkout 與 command execution

---

## 快速開始

在 Codex 中：

```text
使用 chatgpt-codex-collaboration，依照目前 PRD、SDD 與 spec，
讓 ChatGPT 分段實作，Codex 驗收與退修，直到完整 /goal 完成。
```

正常流程：

```text
Mac Doctor
→ Native Goal Gate
→ ChatGPT Chat Mode Gate
→ Create task state
→ CAPABILITY_CHECK
→ Save executor profile
→ Build profile-aware contract
→ Dispatch
→ Start watcher + await
→ Candidate or terminal blocker
→ Codex local acceptance
→ Accept or repair
→ Return to full /goal audit
```

---

## Capability Handshake 範例

```json
{
  "schema_version": "2.0",
  "status": "ready",
  "executor_profile": "github_connector",
  "repository_read": true,
  "repository_write": true,
  "local_checkout": false,
  "shell": false,
  "git_commit": true,
  "git_push": true,
  "external_network": false,
  "can_run_acceptance": false,
  "blocker_code": null,
  "blocker_detail": null,
  "observed_at": "2026-07-11T00:00:00Z"
}
```

保存到 task state：

```sh
sh "$SKILL_ROOT/scripts/task-state.sh" set-executor \
  TASK-001 \
  --file /path/to/handshake.json
```

---

## 狀態機

```text
DISCOVERING
→ CAPABILITY_CHECK
→ READY
→ DISPATCHING
→ IMPLEMENTING
→ WAITING_HANDOFF
→ HANDOFF_CANDIDATE
→ VERIFYING
→ ACCEPTED
```

退修：

```text
VERIFYING
→ REPAIR_REQUIRED
→ WAITING_REPAIR
→ HANDOFF_CANDIDATE
→ VERIFYING
```

主要阻擋狀態：

| 狀態 | 原因 |
|---|---|
| `BLOCKED_GOAL` | Goal 缺失、衝突或非 active |
| `BLOCKED_SPEC` | 必要產品行為未定義 |
| `BLOCKED_CAPABILITY` | ChatGPT 無法建立 candidate，或 Codex 無法驗證 |
| `BLOCKED_TRANSPORT` | ChatGPT／GitHub transport 不可用 |
| `BLOCKED_OBSERVATION` | 無法可靠等待 terminal event |
| `BLOCKED_USER` | 需要使用者決策 |

Task state：

```text
~/.codex/collaboration/tasks/<task-id>.json
```

Transport events：

```text
~/.codex/collaboration/events/<task-id>.jsonl
```

---

## Handoff 驗證

```sh
sh "$SKILL_ROOT/scripts/validate-handoff.sh" \
  <repo-path> <remote> <branch> \
  <base-sha> <candidate-sha> <allowed-path>...
```

檢查：

- candidate 是 assigned branch 的目前 HEAD；
- candidate 與 base SHA 不同；
- changed files 在 allowed scope；
- 沒有 `.env`、private key、壓縮檔或暫存檔。

Branch 更新只代表 candidate，不代表驗收通過。

---

## Goal 與 Task

`ACCEPTED` 只代表一個有限 task 通過。

Codex 必須重新檢查完整 objective、PRD、SDD、spec、repository、runtime、tests、CI、browser checks 與外部狀態。只有全部 requirements 都被證明完成，才能：

```text
update_goal(status="complete")
```

---

## 安全邊界

預設禁止：

- force-push；
- 直接寫入 base branch；
- reset 或丟棄使用者未提交修改；
- 傳送 secrets、token、`.env` 或 private key；
- 修改 allowed paths 外的檔案；
- 未經允許安裝 package；
- ChatGPT 未 push 時，把聊天程式碼當正式交付；
- Codex 驗收失敗後自行修補 ChatGPT 工作；
- `github_connector` 因不能跑 shell 就被錯誤判定失敗；
- ChatGPT 已回報 blocker 後仍持續等待 commit。

---

## 目前邊界

本 repo 已提供：

- native `/goal` binding；
- capability handshake；
- `local_full`／`github_connector` profiles；
- persistent task state；
- blocker-aware local event channel；
- launchd Git watcher；
- low-token blocking await；
- GitHub handoff validation；
- recovery and repair rules。

完整自動化仍需要實際 ChatGPT transport adapter 能：

1. 開啟指定對話；
2. 確認 Chat mode；
3. 讀取 handshake 與 terminal response；
4. 將 blocker 寫入 `transport-event.sh`；
5. 讓 ChatGPT 使用可用的 repository executor。

目前為 **macOS-first experimental workflow**。
