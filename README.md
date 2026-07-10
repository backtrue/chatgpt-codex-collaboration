# ChatGPT–Codex Collaboration

一套 **macOS-first、以 Codex 原生 `/goal` 為上層控制權**的雙代理開發與驗收流程。

ChatGPT 負責有限範圍的程式實作，Codex 負責掌握規格、檢查 Git diff、執行驗收、退回修正，以及持續推進完整目標。GitHub branch 是兩者之間正式且可稽核的交接邊界。

> 目前第一版只支援 macOS 13 Ventura 以上。Linux、Windows 與 WSL 暫不在支援範圍內。

---

## 為什麼需要這個 Skill

單一 AI 同時負責「寫程式」與「宣布自己寫對了」，容易出現幾個問題：

- 測試通過，但實作仍偏離 PRD／SDD／spec。
- 模型完成一個局部 task 後，就把整體工作當成結束。
- 長時間等待 ChatGPT 回覆時，Codex 持續輪詢並消耗大量 token。
- 中途斷線或重啟後，不知道任務是否已派送、做到哪裡、該不該重送。
- ChatGPT 說「完成」，但沒有遠端 commit、測試證據或可驗證的交付。

本 Skill 把角色拆開：

| 角色 | 職責 |
|---|---|
| **Codex `/goal`** | 保存完整目標，跨 turn 自動延續工作 |
| **Codex** | 拆出有限 task、掌握 spec、驗收、退修、決定 goal 是否完成 |
| **ChatGPT** | 依 Task Contract 實作、測試、commit、push |
| **GitHub** | 程式碼與驗收證據的正式交接邊界 |
| **使用者** | 裁決未定義的產品行為與明確的 goal 變更 |

---

## 核心原則

1. **ChatGPT 不得驗收自己的實作。**
2. **Codex 驗收失敗時，不得偷偷代替 ChatGPT 修正。**
3. **ChatGPT 的「完成」訊息不算交付；遠端 branch 與 commit SHA 才算。**
4. **測試通過不等於 spec 通過。**
5. **單一 task 驗收通過，不等於整體 `/goal` 完成。**
6. **等待 ChatGPT 時，不使用 Codex 推理迴圈輪詢。**
7. **Goal、task、branch、base SHA、candidate SHA 與驗收結果都必須可持久化與恢復。**

---

## 架構

```text
Native Codex thread goal (/goal)
  │
  │  objective / status / budget / automatic continuation
  ▼
Codex verifier & orchestrator on macOS
  ├─ Goal Gate: get_goal / create_goal / update_goal
  ├─ Mac Doctor and repository preflight
  ├─ Control Plane: approved ChatGPT conversation
  ├─ State Store: ~/.codex/collaboration/tasks/*.json
  ├─ launchd watcher: ~/Library/LaunchAgents/*.plist
  └─ Data Plane: assigned GitHub branch
          ↑
ChatGPT implementer through the configured executor
```

完整說明見 [`docs/architecture.md`](docs/architecture.md)。

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

所有 shell 檔都只是 macOS `/bin/sh` 的薄包裝，實際邏輯由 Python 執行；**不需要 Homebrew Bash，也不依賴 GNU coreutils**。

---

## 安裝

### 使用者層級安裝

Codex 會掃描 `~/.agents/skills` 中的使用者 Skill：

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

### 專案層級安裝

只讓特定 repository 使用：

```sh
mkdir -p .agents/skills
git clone \
  https://github.com/backtrue/chatgpt-codex-collaboration.git \
  .agents/skills/chatgpt-codex-collaboration
```

安裝後重新開啟或重新載入 Codex session，讓 Skill catalog 更新。

---

## 快速開始

### 1. 執行 Mac Doctor

使用者層級安裝範例：

```sh
SKILL_DIR="$HOME/.agents/skills/chatgpt-codex-collaboration"

sh "$SKILL_DIR/scripts/macos-doctor.sh" \
  --repo "$PWD" \
  --remote origin
```

Doctor 會檢查：

- macOS 版本與 CPU 架構
- Python、Git、Codex CLI
- Xcode Command Line Tools
- `launchctl`、`osascript`、`open`
- Chrome、Safari 或 ChatGPT App
- collaboration state directory 是否可寫
- Git repository 與 remote 是否可連線

詳細安裝與權限說明見 [`docs/macos.md`](docs/macos.md)。

### 2. 在 Codex 中啟動 Skill

可以直接指定 Skill 名稱與完整目標，例如：

```text
使用 chatgpt-codex-collaboration，依照目前 PRD、SDD 與 spec，
讓 ChatGPT 分段實作，Codex 持續驗收與退修，直到整體目標完成。
```

Skill 啟動後會先檢查原生 `/goal`：

- 已有 active goal：綁定既有 `goal_id` 與 objective。
- 沒有 goal，或上一個 goal 已 complete：依使用者真正要求的最終狀態建立新 goal。
- goal 處於 paused、blocked、usage-limited 或 budget-limited：不覆寫，進入 `BLOCKED_GOAL`。
- 既有 active goal 與目前要求衝突：不偷偷替換，交由使用者決定。

### 3. Skill 拆出單一有限 task

每次交給 ChatGPT 的 Task Contract 至少包含：

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
Acceptance commands and observable outcomes
Required handoff fields
```

ChatGPT 必須完成修改、執行驗證、commit 並 push assigned branch。

### 4. launchd 等待 GitHub handoff

等待期間不讓 Codex 持續推理。Skill 會建立 per-task LaunchAgent：

```sh
sh "$SKILL_DIR/scripts/macos-watcher.sh" start \
  TASK-001 \
  chatgpt/TASK-001 \
  <base-sha> \
  --repo "$PWD" \
  --remote origin \
  --dispatch-epoch <unix-epoch>
```

狀態與停止：

```sh
sh "$SKILL_DIR/scripts/macos-watcher.sh" status TASK-001
sh "$SKILL_DIR/scripts/macos-watcher.sh" stop TASK-001
```

LaunchAgent：

```text
~/Library/LaunchAgents/com.backtrue.chatgpt-codex.<task-id>.plist
```

Logs：

```text
~/.codex/collaboration/logs/
```

Watcher 只執行 Git transport 查詢，不呼叫 LLM。

---

## 完整工作流

```text
Mac Doctor
  ↓
Native /goal Gate
  ↓
ChatGPT Chat Mode Gate
  ↓
Repository and capability preflight
  ↓
Create persistent task state
  ↓
Dispatch one goal-aligned task to ChatGPT
  ↓
launchd watches assigned GitHub branch
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
| `BLOCKED_GOAL` | 原生 goal 缺失、狀態不允許、或 goal ID 不一致 |
| `BLOCKED_SPEC` | 必要產品行為未在 spec 定義 |
| `BLOCKED_CAPABILITY` | 缺少 browser、executor 或驗收能力 |
| `BLOCKED_DEPENDENCY` | 缺少必要 command、Skill 或工具 |
| `BLOCKED_TRANSPORT` | 無法存取 ChatGPT 對話或 GitHub transport |
| `BLOCKED_OBSERVATION` | 無法可靠判斷 ChatGPT 或 watcher 狀態 |
| `BLOCKED_USER` | 必須由使用者做產品或 goal 決策 |

Task state 預設存放於：

```text
~/.codex/collaboration/tasks/<task-id>.json
```

非法狀態跳轉會被 `scripts/task-state.py` 拒絕；例如 `WAITING_HANDOFF → ACCEPTED` 不被允許。

---

## Handoff 驗證

候選 commit 出現後，Codex 會執行：

```sh
sh "$SKILL_DIR/scripts/validate-handoff.sh" \
  <repo-path> \
  <remote> \
  <branch> \
  <base-sha> \
  <candidate-sha> \
  <allowed-path>...
```

檢查內容包括：

- candidate SHA 是否為 assigned remote branch 的目前 HEAD
- candidate 是否不同於 base SHA
- changed files 是否在 allowed scope
- 是否混入 `.env`、private key、壓縮檔或暫存檔
- repository 與 remote 是否可驗證

Branch 變更只代表「有候選交付」，不代表驗收通過。

---

## Goal 與 Task 的差別

`ACCEPTED` 只代表一個有限 task 通過，並不代表 `/goal` 完成。

每個 task 驗收後，Codex 必須重新檢查：

- 原始完整 objective
- PRD、SDD、spec、issue 與 plan
- repository 與 runtime 狀態
- tests、CI、browser checks、artifacts 與外部狀態
- 哪些 requirement 已有直接證據
- 哪些 requirement 尚未完成或未驗證

只有全部要求都被證明完成，才能呼叫：

```text
update_goal(status="complete")
```

否則 goal 必須保持 active，並由 Codex 繼續下一個 task 或交回原生 goal runtime 自動續跑。

詳見 [`docs/goal-integration.md`](docs/goal-integration.md)。

---

## 安全邊界

本 Skill 預設禁止：

- force-push
- 直接寫入 base branch
- reset 或丟棄使用者未提交的修改
- 讀取或傳送 secrets、token、`.env` 與 private key
- 修改未列入 allowed paths 的檔案
- 未經允許安裝 package
- ChatGPT 未 push 時，把聊天中的程式碼直接當成正式交付
- Codex 驗收失敗後自行修補 ChatGPT 的工作
- 因為工作很慢、困難或不確定，就把 goal 標成 blocked

macOS Automation／Accessibility 權限應採最小授權；不要為了通過 preflight 而直接授予 Full Disk Access。

---

## Repository 結構

```text
.
├── SKILL.md
├── README.md
├── dependencies.yaml
├── agents/
│   └── openai.yaml
├── config/
│   └── executor.example.yaml
├── contracts/
│   └── collaboration.schema.json
├── docs/
│   ├── architecture.md
│   ├── goal-integration.md
│   └── macos.md
└── scripts/
    ├── macos-doctor.py
    ├── macos-doctor.sh
    ├── macos-watcher.py
    ├── macos-watcher.sh
    ├── preflight.py
    ├── preflight.sh
    ├── task-state.py
    ├── task-state.sh
    ├── validate-handoff.py
    ├── validate-handoff.sh
    ├── wait-for-handoff.py
    └── wait-for-handoff.sh
```

---

## 目前邊界

macOS orchestration core 已包含：

- 原生 `/goal` 綁定與延續
- Task Contract 與 Repair Contract
- persistent state machine
- macOS Doctor
- repository preflight
- launchd watcher
- GitHub handoff validation
- token-efficient waiting
- restart／recovery rules

完整自動化仍要求執行環境實際提供：

1. **ChatGPT transport adapter**：能開啟指定對話、辨識 Chat mode、送出 idempotent task、判斷生成或終止狀態。
2. **ChatGPT code executor**：能讓 ChatGPT 修改本機 worktree、執行 command、commit 與 push。

缺少前者會進入 `BLOCKED_TRANSPORT`；缺少後者會進入 `BLOCKED_CAPABILITY`。Skill 不會假裝這些能力存在。

---

## 開發狀態

目前為 **macOS-first experimental workflow**。建議先在測試 repository 使用，確認 Doctor、Goal tools、ChatGPT transport、executor、GitHub 權限與 launchd watcher 都能正常運作，再投入重要專案。
