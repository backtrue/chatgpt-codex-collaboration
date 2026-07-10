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
- Task capability blocker 被誤升級成 native goal blocked／paused，導致整體工作停止。

本 Skill 將角色拆開：

| 角色 | 職責 |
|---|---|
| **Codex `/goal`** | 保存完整目標，跨 turn 延續工作 |
| **Codex** | 拆 task、掌握 spec、驗收、退修、判斷 goal 是否完成 |
| **ChatGPT** | 依 Task Contract 實作、測試或建立待驗證 candidate、commit、push |
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
8. **Task blocked 不等於 native goal blocked。**
9. Skill 不得自動執行 `/goal pause`、`/goal clear` 或因 task failure 呼叫 `update_goal(blocked)`。

---

## Native Goal Safety

Native goal 與 collaboration task 是兩套不同的 state machine。

以下都只是 task-local 狀態：

```text
CAPABILITY_CHECK
WAITING_HANDOFF
BLOCKED_CAPABILITY
BLOCKED_TRANSPORT
BLOCKED_OBSERVATION
BLOCKED_SPEC
BLOCKED_USER
REPAIR_REQUIRED
```

進入這些狀態時，native `/goal` 應保持原狀。尤其是：

```text
ChatGPT 沒有本機 checkout／shell
＋
仍可透過 GitHub connector 建立 commit
```

正確處理是：

```text
停止舊 watcher
→ task 回到 CAPABILITY_CHECK
→ 重新 handshake
→ 選 github_connector
→ ChatGPT 建立未測試 candidate
→ Codex 本機驗證
```

不是：

```text
update_goal(blocked)
或
/goal pause
```

Native goal 只有在同一個「完整目標 blocker」跨至少三個 native goal turns 持續存在、且沒有 executor fallback、transport fallback、repair 或本機驗證路徑時，才可標成 blocked。

詳見 [`docs/native-goal-safety.md`](docs/native-goal-safety.md)。

---

## 架構

```text
Native Codex thread goal (/goal)
  │
  │ objective / status / budget / continuation
  ▼
Codex verifier & orchestrator on macOS
  ├─ Goal Gate and Native Goal Safety
  ├─ Mac Doctor and repository preflight
  ├─ ChatGPT capability handshake
  ├─ Control Plane: approved ChatGPT conversation
  ├─ State Store: ~/.codex/collaboration/tasks/*.json
  ├─ launchd Git watcher
  ├─ blocking local await
  └─ Data Plane: assigned GitHub branch
          ↑
ChatGPT implementer through local_full or github_connector
```

完整設計見 [`docs/architecture.md`](docs/architecture.md)。

---

## Executor Profiles

正式派工前，ChatGPT 必須先回傳 capability handshake。

| Profile | ChatGPT 行為 | Codex 行為 |
|---|---|---|
| `local_full` | 本機修改、focused checks、commit、push | 重跑驗收 |
| `github_connector` | 透過 connector 修改並建立 candidate，測試可 `not_run` | 本機跑完整驗收 |
| `read_only` | 無法建立 candidate | Task `BLOCKED_CAPABILITY`，goal 不變 |
| `none` | 無可用 executor | Task `BLOCKED_CAPABILITY`，goal 不變 |

在 `github_connector` 模式下，ChatGPT 沒有 shell 不是 blocker；測試責任延後到 Codex。

詳見 [`docs/capability-handshake.md`](docs/capability-handshake.md)。

---

## 真正的低 Token 等待

背景 watcher 執行 `git ls-remote` 本身不會呼叫模型。真正的 token 風險是 active `/goal` 在 thread idle 時反覆啟動 continuation turn。

修正後使用兩層等待：

```text
launchd watcher
  └─ 低頻、漸進退避地監看 GitHub branch

目前的 Codex turn
  └─ 阻塞在本機 await，只讀 watcher log 與 transport event
```

啟動 watcher：

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" start \
  TASK-001 chatgpt/TASK-001 <base-sha> \
  --repo "$PWD" \
  --remote origin \
  --dispatch-epoch <unix-epoch>
```

接著立即阻塞目前 turn：

```sh
sh "$SKILL_ROOT/scripts/macos-watcher.sh" await \
  TASK-001 --timeout-seconds 7500
```

`await` 同時監看：

- Git handoff candidate
- ChatGPT terminal blocker
- conversation completed without commit
- transport failure
- mode drift
- watcher failure

因此 ChatGPT 已明確表示無法交件時，Codex 不會繼續傻等 lease 到期。

---

## 支援環境

- macOS 13 Ventura 以上
- Apple Silicon `arm64` 或 Intel `x86_64`
- Python 3.9 以上
- Git 2.30 以上
- Xcode Command Line Tools
- Codex CLI 與原生 Goal tools
- 可連線並具有 push 權限的 GitHub remote
- Codex 可本機讀取完整 repository 並執行驗收命令
- Codex 可存取指定 ChatGPT 對話
- ChatGPT 至少具有 `local_full` 或 `github_connector` profile

所有 shell 檔都只是 `/bin/sh` 薄包裝，主要邏輯由 Python 執行。

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

安裝後重新載入 Codex session。

---

## 快速開始

```sh
SKILL_ROOT="$HOME/.agents/skills/chatgpt-codex-collaboration"

sh "$SKILL_ROOT/scripts/macos-doctor.sh" \
  --repo "$PWD" \
  --remote origin
```

在 Codex 中：

```text
使用 chatgpt-codex-collaboration，依照目前 PRD、SDD 與 spec，
讓 ChatGPT 分段實作，Codex 持續驗收與退修，直到整體目標完成。
```

流程：

```text
Mac Doctor
→ Native /goal Gate
→ ChatGPT Chat Mode Gate
→ Create task state
→ Capability handshake
→ Select local_full or github_connector
→ Dispatch profile-aware task
→ Start watcher and blocking await
→ Candidate or terminal transport event
→ Codex acceptance / capability recovery
→ Return to complete goal audit
```

---

## 恢復舊版誤標 blocked／paused 的 Goal

若舊版 Skill 已經把 native goal 誤標成 blocked 或 paused：

1. 更新 Skill：

   ```sh
   git -C "$HOME/.agents/skills/chatgpt-codex-collaboration" pull
   ```

2. 保留原本 goal ID 與 objective，不建立新 goal。
3. 在 Codex 使用原生 `/goal resume` 恢復同一目標。
4. 找到 task ID 後執行：

   ```sh
   sh "$SKILL_ROOT/scripts/recover-capability.sh" <task-id>
   ```

5. 重新執行 capability handshake。
6. 若 GitHub connector 可 commit，改用 `github_connector` 合約繼續。

Recovery command 會：

- 停止舊 watcher
- 清除舊 terminal events
- 保留 goal、branch、base SHA 與 task history
- 將 task 送回 `CAPABILITY_CHECK`
- 不修改 native goal

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

Task-local blocked states 不得直接改變 native goal status。

---

## Handoff 驗證

```sh
sh "$SKILL_ROOT/scripts/validate-handoff.sh" \
  <repo-path> <remote> <branch> <base-sha> <candidate-sha> <allowed-path>...
```

Branch 更新只代表候選交付，不代表驗收通過。

---

## Goal 與 Task

`ACCEPTED` 只代表一個有限 task 通過。

只有完整 objective、PRD、SDD、spec、repository、runtime、tests、CI、browser checks 與外部狀態全部有直接證據時，才可以：

```text
update_goal(status="complete")
```

否則 goal 保持 active，繼續下一個 task。

---

## 安全邊界

預設禁止：

- force-push
- 直接寫入 base branch
- reset 或丟棄使用者未提交修改
- 傳送 secrets、token、`.env` 與 private key
- 修改 allowed paths 之外的檔案
- 未經允許安裝 package
- ChatGPT 未 push 時，把聊天程式碼當成正式交付
- Codex 驗收失敗後自行修補 ChatGPT 的工作
- 等待 handoff 時反覆產生「仍在等待」goal turns
- 因 task capability／transport blocker 自動把 native goal blocked 或 paused

---

## 目前邊界

macOS orchestration core 已包含：

- native `/goal` 綁定與 safety policy
- capability handshake
- `local_full`／`github_connector` profile
- persistent task state
- Mac Doctor 與 repository preflight
- launchd watcher 與 blocking await
- transport terminal events
- capability recovery
- GitHub handoff validation

完整自動化仍需要 ChatGPT transport adapter 能開啟對話、辨識 Chat mode、發送 task，並在 terminal response 時寫入 transport event。

目前為 **macOS-first experimental workflow**。建議先在測試 repository 驗證完整流程，再投入重要專案。
