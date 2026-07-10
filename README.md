# ChatGPT–Codex Collaboration

一套 **macOS-first、以 Codex 原生 `/goal` 為上層控制權**的雙代理開發與驗收流程。

ChatGPT 負責有限範圍的程式實作；Codex 負責掌握 PRD／SDD／spec、檢查 Git diff、執行驗收、退回修正，並持續推進完整目標。GitHub branch 是兩者之間正式且可稽核的交接邊界。

> 第一版只支援 macOS 13 Ventura 以上。Linux、Windows 與 WSL 暫不支援。

---

## 為什麼需要這個 Skill

單一 AI 同時負責寫程式與宣布自己寫對了，常見問題包括：

- 測試通過，但實作仍偏離 spec。
- 模型完成一個局部 task，就把整體工作當成結束。
- ChatGPT 說完成，但沒有遠端 commit 與可驗證證據。
- 驗收失敗後，Codex 直接代替 ChatGPT 修掉，失去獨立驗收。
- 中途斷線或重啟後，不知道任務是否已派送、是否該重送。
- 等待 ChatGPT 時，active `/goal` 反覆產生 continuation turn，持續消耗 token。

本 Skill 將角色拆開：

| 角色 | 職責 |
|---|---|
| **Codex `/goal`** | 保存完整目標，跨 turn 延續工作 |
| **Codex** | 拆 task、掌握 spec、驗收、退修、判斷 goal 是否完成 |
| **ChatGPT** | 依 Task Contract 實作、測試、commit、push |
| **GitHub** | 程式碼與驗收證據的正式交接邊界 |
| **使用者** | 裁決未定義的產品行為與 goal 變更 |

---

## 核心原則

1. ChatGPT 不得驗收自己的實作。
2. Codex 驗收失敗時，不得偷偷代替 ChatGPT 修正。
3. ChatGPT 的「完成」訊息不算交付；遠端 branch 與 commit SHA 才算。
4. 測試通過不等於 spec 通過。
5. 單一 task 驗收通過，不等於整體 `/goal` 完成。
6. 等待 ChatGPT 時，不使用 Codex reasoning loop 輪詢。
7. Goal、task、branch、SHA 與驗收結果都必須可持久化與恢復。

---

## 架構

```text
Native Codex thread goal (/goal)
  │
  │ objective / status / budget / continuation
  ▼
Codex verifier & orchestrator on macOS
  ├─ Goal Gate: get_goal / create_goal / update_goal
  ├─ Mac Doctor and repository preflight
  ├─ Control Plane: approved ChatGPT conversation
  ├─ State Store: ~/.codex/collaboration/tasks/*.json
  ├─ launchd Git watcher
  ├─ blocking local await — keeps the Codex turn active
  └─ Data Plane: assigned GitHub branch
          ↑
ChatGPT implementer through the configured executor
```

完整設計見 [`docs/architecture.md`](docs/architecture.md)。

---

## 真正的低 Token 等待

### 問題不只是 Git polling

背景 watcher 執行 `git ls-remote` 本身不會呼叫模型，也不會直接消耗 Codex token。

真正的 token 風險是：active `/goal` 在 thread idle 時會自動啟動 continuation turn。若 Codex 每次醒來只發現 ChatGPT 還沒交件，流程可能變成：

```text
Codex turn 結束
→ thread idle
→ /goal 自動開新 turn
→ 發現仍在等待
→ turn 結束
→ 再次 idle
→ 重複
```

### 修正後的兩層等待

```text
launchd watcher
  └─ 低頻、漸進退避地監看 GitHub branch

目前的 Codex turn
  └─ 阻塞在本機 await，只讀 watcher log
```

啟動 watcher：

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" start \
  TASK-001 \
  chatgpt/TASK-001 \
  <base-sha> \
  --repo "$PWD" \
  --remote origin \
  --dispatch-epoch <unix-epoch>
```

接著立即阻塞目前 turn：

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" await \
  TASK-001 \
  --timeout-seconds 7500
```

`await`：

- 只讀本機 log，不查 GitHub。
- 不呼叫 LLM。
- 保持目前 Codex turn 為 active。
- 避免 `/goal` 因 idle 而反覆啟動新 turn。
- 只在 candidate commit、lease expiry、interrupt 或 watcher failure 時返回。

Git watcher 預設：

- 初始 polling：60 秒。
- 連續無變化後漸進退避。
- 最大 polling：300 秒。
- 只記錄狀態變化，不記錄每一次 poll。

因此：

> **Watcher 可以持續負責任務，但 Codex 不需要持續思考任務。**

---

## 支援環境

- macOS 13 Ventura 以上
- Apple Silicon `arm64` 或 Intel `x86_64`
- Python 3.9 以上
- Git 2.30 以上
- Xcode Command Line Tools
- Codex CLI，且目前 thread 可使用原生 Goal tools
- 可連線並具有 push 權限的 GitHub remote
- Codex 可存取指定 ChatGPT 對話
- ChatGPT 端具有可修改 repository、執行測試、commit 與 push 的 executor

所有 shell 檔都只是 `/bin/sh` 薄包裝，主要邏輯由 Python 執行；不需要 Homebrew Bash 或 GNU coreutils。

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

安裝後重新載入 Codex session，讓 Skill catalog 更新。

---

## 快速開始

### 1. 設定 Skill 路徑

使用者層級安裝：

```sh
SKILL_ROOT="$HOME/.agents/skills/chatgpt-codex-collaboration"
```

所有 bundled scripts 都應以 Skill 絕對路徑執行；不要假設目前工作目錄是 Skill repository。

### 2. 執行 Mac Doctor

```sh
sh "$SKILL_ROOT/scripts/macos-doctor.sh" \
  --repo "$PWD" \
  --remote origin
```

Doctor 會檢查 macOS、CPU 架構、Python、Git、Codex CLI、Xcode Command Line Tools、launchd、ChatGPT surface、state directory 與 GitHub remote。

詳細說明見 [`docs/macos.md`](docs/macos.md)。

### 3. 在 Codex 中啟動

```text
使用 chatgpt-codex-collaboration，依照目前 PRD、SDD 與 spec，
讓 ChatGPT 分段實作，Codex 持續驗收與退修，直到整體目標完成。
```

Skill 會先檢查原生 `/goal`：

- 有 active goal：綁定既有 goal。
- 沒有 goal／上一個已 complete：依完整終局目標建立新 goal。
- goal paused、blocked、usage-limited 或 budget-limited：不覆寫，進入 `BLOCKED_GOAL`。
- active goal 與目前要求衝突：交由使用者決定。

### 4. 派送單一有限 task

Task Contract 至少包含：

```text
Parent goal ID
Goal objective
Goal contribution
Task ID and objective
Repository
Branch
Base SHA
Authoritative spec references
Allowed files
Forbidden changes
Acceptance commands and outcomes
Required handoff fields
```

ChatGPT 必須修改、測試、commit 並 push assigned branch。

---

## 完整流程

```text
Mac Doctor
  ↓
Native /goal Gate
  ↓
ChatGPT Chat Mode Gate
  ↓
Repository preflight
  ↓
Create persistent task state
  ↓
Dispatch one goal-aligned task
  ↓
Start launchd watcher
  ↓
Block current Codex turn in local await
  ↓
Candidate commit appears
  ↓
Validate branch / SHA / changed-file scope
  ↓
Codex acceptance
  ├─ Pass → TASK ACCEPTED
  └─ Fail → Repair Contract → ChatGPT → repeat
  ↓
Return to full native /goal audit
  ├─ All requirements proven → update_goal(complete)
  └─ Work remains → keep goal active and continue
```

---

## 狀態機

正常 task：

```text
DISCOVERING
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

阻擋狀態：

| 狀態 | 意義 |
|---|---|
| `BLOCKED_GOAL` | 原生 goal 缺失、狀態不允許或 goal ID 不一致 |
| `BLOCKED_SPEC` | 必要產品行為未定義 |
| `BLOCKED_CAPABILITY` | 缺少 browser、executor 或驗收能力 |
| `BLOCKED_DEPENDENCY` | 缺少必要 command、Skill 或工具 |
| `BLOCKED_TRANSPORT` | 無法存取 ChatGPT 或 GitHub transport |
| `BLOCKED_OBSERVATION` | 無法低成本、可靠地等待外部 handoff |
| `BLOCKED_USER` | 必須由使用者做產品或 goal 決策 |

Task state 預設位於：

```text
~/.codex/collaboration/tasks/<task-id>.json
```

非法跳轉，例如 `WAITING_HANDOFF → ACCEPTED`，會被 state controller 拒絕。

---

## Handoff 驗證

```sh
sh "$SKILL_ROOT/scripts/validate-handoff.sh" \
  <repo-path> \
  <remote> \
  <branch> \
  <base-sha> \
  <candidate-sha> \
  <allowed-path>...
```

驗證內容：

- candidate 是否為 assigned remote branch 的目前 HEAD
- candidate 是否不同於 base SHA
- changed files 是否在 allowed scope
- 是否混入 `.env`、private key、壓縮檔或暫存檔
- repository 與 remote 是否可驗證

Branch 更新只代表候選交付，不代表驗收通過。

---

## Goal 與 Task

`ACCEPTED` 只代表一個有限 task 通過。

每個 task 驗收後，Codex 必須重新檢查完整 objective、PRD、SDD、spec、repository、runtime、tests、CI、browser checks、artifacts 與外部狀態。

只有全部 requirement 都被證明完成，才可以：

```text
update_goal(status="complete")
```

否則 goal 保持 active，繼續下一個 task。

詳見 [`docs/goal-integration.md`](docs/goal-integration.md)。

---

## 安全邊界

預設禁止：

- force-push
- 直接寫入 base branch
- reset 或丟棄使用者未提交修改
- 讀取或傳送 secrets、token、`.env` 與 private key
- 修改 allowed paths 之外的檔案
- 未經允許安裝 package
- ChatGPT 未 push 時，把聊天程式碼當成正式交付
- Codex 驗收失敗後自行修補 ChatGPT 的工作
- 因為工作慢或困難就把 goal 標成 blocked
- 等待 handoff 時反覆產生「仍在等待」的 goal turns

macOS Automation／Accessibility 權限應採最小授權，不應為了通過 preflight 而直接授予 Full Disk Access。

---

## Repository 結構

```text
.
├── SKILL.md
├── README.md
├── dependencies.yaml
├── agents/openai.yaml
├── config/executor.example.yaml
├── contracts/collaboration.schema.json
├── docs/
│   ├── architecture.md
│   ├── goal-integration.md
│   └── macos.md
└── scripts/
    ├── macos-doctor.py
    ├── macos-watcher.py
    ├── preflight.py
    ├── task-state.py
    ├── validate-handoff.py
    └── wait-for-handoff.py
```

---

## 目前邊界

macOS orchestration core 已包含：

- 原生 `/goal` 綁定與延續
- Task／Repair Contract
- persistent state machine
- Mac Doctor 與 repository preflight
- launchd Git watcher
- blocking local await
- adaptive polling backoff
- GitHub handoff validation
- restart／recovery rules

完整自動化仍需要實際執行環境提供：

1. **ChatGPT transport adapter**：開啟指定對話、辨識 Chat mode、送出 idempotent task、判斷生成狀態。
2. **ChatGPT code executor**：讓 ChatGPT 修改 worktree、執行 command、commit 與 push。

缺少前者會進入 `BLOCKED_TRANSPORT`；缺少後者會進入 `BLOCKED_CAPABILITY`。

目前為 **macOS-first experimental workflow**。建議先在測試 repository 驗證完整流程，再投入重要專案。
