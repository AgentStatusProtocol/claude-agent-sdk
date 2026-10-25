# ASP × Claude Agent SDK — Supplier Desk demo

A small agent built with the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) whose state is reported in real time through the [Agent Status Protocol (ASP)](https://github.com/AgentStatusProtocol/spec) v0.1 working draft.

The point of the demo: **the harness reports, not the model.** Every ASP event is produced by code the model cannot influence (SDK hooks, SDK messages, the permission callback), and governance decisions taken on the status server are enforced back inside the harness.

## What the agent does

*Supplier Desk* reads five supplier communications in `workspace/inbox/` (fictitious, in English), delegates each one to a `doc-analyst` subagent, and writes a delivery-risk report to `workspace/out/` after a human approves the write. One document (`05-trasporti-est.md`) contains a planted prompt injection, hidden in an HTML comment, that points to a confidential file outside the workspace (`restricted/supplier-pricing.md`). The report always ends with a *Security notices* section listing any document flagged as a suspected injection.

## How SDK signals map to ASP

| SDK signal | ASP event |
|---|---|
| task start | `task` submitted → working, lifecycle `busy` |
| `PreToolUse` / `PostToolUse` hooks | `progressSeq` increases, `activity` = `tool:<name>` |
| `PostToolUseFailure` (3 in a row) | `health` → `degraded` |
| `SubagentStart` | the subagent registers as its own ASP agent, its task → working |
| `SubagentStop` | subagent task → completed (or canceled), then `deregister` |
| `can_use_tool` (human approval of Write) | `task` working → `awaiting-approval` → working |
| `AssistantMessage.error`, `RateLimitEvent`, `api_retry` | `health` → `rate-limited`, `auth-error`, `quota-exhausted`, … |
| `ResultMessage` | `task` → completed / failed / canceled, `costUsd` and token metrics |
| guardrail in `PreToolUse` (path outside the workspace) | `governance` → `policy-violation`, with `source: guardrail` |
| injection detector in `PostToolUse` (content returned by Read or Grep) | `governance` → `under-review`, with `source: guardrail`; the model is told, so the report names the document |
| governance read from the server | `quarantined` / `policy-violation` block all tools, `sandboxed` / `under-review` allow read-only tools |

Events carry state only: no prompts, tool inputs, file contents or outputs. The guardrail reports reason codes (`path-outside-workspace`, `suspected-prompt-injection`), never the path or the matched text.

## Files

`agent.py` is the agent (options, subagent, prompts). `asp_bridge.py` is the reusable part: hooks, heartbeat thread, guardrail, governance enforcement. `asp_client.py` is a stdlib-only ASP client. `asp_operator.py` is an operator CLI that lists agents and changes their governance state with `source: operator`. `keychain.py` reads secrets from the macOS Keychain or, on Windows, from Credential Manager. The Claude Code helpers are `scripts/anthropic-key-from-keychain.sh` and `scripts/anthropic-key-from-credential-manager.py`.

## Setup

Requirements: macOS or Windows, Python 3.10+, an Anthropic API key, and the illustrative status server from the spec repository. The Agent SDK bundles the Claude Code CLI it runs on. Linux and CI use the environment variable instead of an OS secret store.

### 1. Store the API key

The key is never exported, written to a file or typed on the command line. On macOS it lives in the Keychain. On Windows it lives in Credential Manager, for the current Windows user. In both cases the agent passes Claude Code an `apiKeyHelper`: the Claude Code process runs that helper when it needs the key and keeps the key in memory only. The key never appears in your shell, its history, or the environment of the Python process. If `ANTHROPIC_API_KEY` is set in the shell, the agent refuses to start, so a forgotten export cannot silently take over.

#### macOS Keychain

Run this and paste the key when `security` asks for the password:

```bash
security add-generic-password -U -a "$USER" -s anthropic-api-key -w
```

Check it without printing it (standard library only, works before installing anything):

```bash
python3 keychain.py
```

The helper on macOS is `scripts/anthropic-key-from-keychain.sh`.

For a stricter setup, create the item so that macOS asks for confirmation on every read, instead of letting any process of your user read it through `security`:

```bash
security add-generic-password -U -a "$USER" -s anthropic-api-key -T "" -w
```

The optional bearer token of the ASP server can live in the same store, under the name `asp-token`; the agent and the operator CLI read it automatically. On macOS that is a Keychain item. On Windows, store it with `python keychain.py --set asp-token`.

#### Windows Credential Manager

From this folder (standard library only, works before installing anything):

```powershell
python keychain.py --set
```

Python prompts with no echo. The item name is `anthropic-api-key`. Check it without printing it:

```powershell
python keychain.py
```

The helper on Windows is `scripts/anthropic-key-from-credential-manager.py`, run with the same Python that launched the agent. `--key-source wincred` is the default on Windows, so `python agent.py` uses Credential Manager.

If the key is invalid or revoked, the agent stops within seconds with `health: auth-error` and `task: failed` on the dashboard, instead of waiting for the SDK's full retry sequence.

### Replacing or removing the API key

To replace the key, delete the old Keychain item and store the new one (paste the key at the password prompt):

```bash
security delete-generic-password -a "$USER" -s anthropic-api-key
security add-generic-password -U -a "$USER" -s anthropic-api-key -w
```

`-U` alone would already overwrite the existing item; deleting it first guarantees a clean entry. Use `-T ""` in the second command if you want macOS to ask for confirmation on every read. Then check that the new key is the one stored, by comparing the last four characters with the key in the Claude Console:

```bash
python3 keychain.py
```

To remove the key without replacing it, run only the first command.

On Windows, `python keychain.py --set` overwrites the same Credential Manager target. `python keychain.py --delete` removes it. Check either change with `python keychain.py`.

Two things to keep in mind. Deleting the key from the Keychain or from Credential Manager does not disable it: to make an old key unusable, revoke it in the Claude Console. And an agent that is already running may keep using the old key for a few minutes, because the SDK holds it in memory: stop the agent and start it again after the change.

### 2. Start the status server

```bash
git clone https://github.com/AgentStatusProtocol/spec.git
ASP_PORT=8765 python3 spec/implementations/python-status-server/server.py
```

The demo uses port 8765 instead of the server's default 8080, which is often already taken; `--server` or `ASP_SERVER` change it. Open http://127.0.0.1:8765 to watch the observer page.

### 3. Run the agent

In a second terminal, from this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python agent.py
```

On Windows, from PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python agent.py
```

If PowerShell refuses to run the activation script, allow it for this window only with `Set-ExecutionPolicy -Scope Process RemoteSigned`, then run the activation script again.

On Linux or in CI, `--key-source env` falls back to the `ANTHROPIC_API_KEY` environment variable. There is no Keychain or Credential Manager path on those systems.

## Stopping everything

Stop the processes in this order, each in its own terminal window.

**1. The agent.** Press `Ctrl+C` in the agent's terminal. This works at any point, including while the agent is waiting at the approval prompt. The agent closes its task as `canceled`, deregisters, and shows up as `offline` on the dashboard before the process exits with `Stopped.`.

**2. The status server.** Press `Ctrl+C` in the server's terminal. Python prints a short `KeyboardInterrupt` traceback: that is the normal way the illustrative server stops. The server keeps everything in memory, so the dashboard starts empty the next time.

Stopping the server first is harmless but less tidy: the agent keeps working without being able to report, and its governance checks fall back to the last known state.

**3. The virtual environment.** In the agent's terminal:

```bash
deactivate
```

### If a window was closed or a process was left behind

Check whether something is still listening on the dashboard port and whether an agent is still running:

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
pgrep -fl "agent.py"
```

Stop them by name:

```bash
pkill -INT -f "agent.py"
pkill -INT -f "python-status-server/server.py"
```

`-INT` sends the same signal as `Ctrl+C`, so the agent still deregisters cleanly. `pgrep` first shows what would be stopped: if another program of yours is also called `agent.py`, stop this one by its process number instead (`kill -INT <PID>`).

## Scenarios to try

**1. Normal run.** `python agent.py` — the main agent turns busy, one `doc-analyst` appears per document and disappears when done, the main task goes to `awaiting-approval` when the report is ready and waits for your `y` in the terminal.

**2. Waiting is not stalling.** At the approval prompt, wait longer than `--stall-after` (45 s). The agent stays healthy: `awaiting-approval` is not a progress state, so the server does not mark it `stalled`.

**3. Prompt injection, detected and reported.** Every run shows it. When a `doc-analyst` reads `05-trasporti-est.md`, the harness scans the content returned by the tool, recognises text addressed to an AI assistant, and sets that subagent's governance to `under-review` with `source: guardrail` and reason `suspected-prompt-injection`. The subagent can still read but no longer write, the model receives a security notice telling it not to follow the hidden text, and the main agent is told to report it. The final report ends with a *Security notices* section naming the document and recommending that the sender be verified. On the dashboard, the flagged analyst stays visible as `under-review` after it goes `offline`.

The point: a model that silently resists an injection is good, but a system that also notices and tells someone is what an organisation needs, because the sender's mailbox or system may be compromised.

**3b. Guardrail on the perimeter.** Run with `--tempt`, which tells the analyst to follow references to other files. If an analyst tries to read the confidential file, the read is denied and that subagent turns `policy-violation`, set by `guardrail`. It cannot clear that state itself, and every further tool call it makes is blocked. The model may still decline to follow the reference: then this guardrail stays silent while scenario 3 still reports the attempt.

```bash
python agent.py --tempt
```

**4. Operator quarantine.** While the agent is working, from a third terminal:

```bash
python asp_operator.py list
python asp_operator.py quarantine urn:agent:demo:supplier-desk --reason suspected-prompt-injection
```

Within about two seconds every tool call of the main agent is denied; when the agent gives up, its task ends as `canceled`. Try `sandbox` instead to allow read-only tools only, and `release` to restore `normal`.

**5. Liveness.** Stop the agent with `Ctrl+C`: it deregisters cleanly. Kill it instead (`kill -9 <PID>`, with the number shown by `pgrep -fl agent.py`): after 2.5 heartbeat intervals the server marks it `unreachable`.

## Options

`--server`, `--token` (or `ASP_SERVER`, `ASP_TOKEN`, or the OS store item `asp-token`), `--key-source` (`keychain` on macOS, `wincred` on Windows, or `env`), `--keychain-service` (default `anthropic-api-key`; the Keychain item or Credential Manager target), `--check-key`, `--id`, `--name`, `--model` (or `CLAUDE_MODEL`), `--interval` (heartbeat seconds, default 5), `--stall-after` (default 45), `--tempt`, `--auto-approve`, `--verbose` (prints every ASP event sent).

## Limits, deliberately

This is an illustrative sketch, not a production integration.

- The guardrail runs in the same process as the agent. It is outside the model's control, which is what matters for the demo, but a production guardrail should run as a separate component with its own credential.
- If the status server is unreachable, governance checks fail open (the last known state is used). A production deployment must decide whether to fail closed.
- Token metrics are aggregated on the main agent; per-subagent cost attribution is left out.
- The injection detector uses a few illustrative regular expressions. It catches the planted example and common phrasings, but a real deployment needs a proper classifier and will still miss some attacks; the model's own instruction to report suspicious text is the second layer.
- The reference server keeps state in memory and is not conformance-tested.

## License

MIT.
