[Uploading STABILIZATION_CHANGELOG.md…]()
# Lily stabilization — what changed, why, and how to check it

**Current version: 1.1.0.** (1.0.0 was the first stabilised release delivered earlier; it carried no version label in the code. 1.1.0 adds file logging, `--version` and `--status`, described first below. Everything else in this document describes 1.0.0 and is unchanged.)

---

## Version 1.1.0 — structured logging, version information, status report

Only these three features were added. No existing behaviour or configuration was changed; your data files and `config/api_keys.json` are byte-identical to the previous package. The VPN project is untouched.

### 1. Structured logging
* **Changed files:** new `lily_log.py`; hooks in `Lily.py`, `lily_runtime.py`, `safety.py`, `system_actions.py`, `system_tools.py`, `core/action_loader.py`, `core/plugin_loader.py`, `voice_manager.py`, `lily_audio.py`, `lily_gui.py`; `lily_config.py` (3 new optional settings); `selftest.py` (new "Logging" check).
* **What:** every run writes `logs\lily.log` (rotating, 1 MB × 3 backups). Each line: `2026-10-10 15:30:02.123 | ERROR    | lily.runtime | MainThread | message`, plus a full traceback for errors. Uncaught exceptions in the main thread **and in worker threads** are logged as CRITICAL before anything else. Recorded events: start/stop with version, local-engine failures (not configured / timeout / crash / unexpected), identity-guard rewrites, every safety decision (confirmation requested / confirmed / cancelled / expired / refused remote or voice reply), refused deletes of protected paths, scheduled/cancelled shutdowns, `taskkill` results, action and plugin crashes / timeouts / rejections, voice and wake-word problems, GUI worker failures.
* **Privacy:** the log records *what happened*, never *what you said* (a test proves message text does not appear, even at DEBUG).
* **Settings** (optional, in `config\local_settings.json`): `log_level` (DEBUG/INFO/WARNING/ERROR, default INFO), `log_max_bytes` (default 1000000, minimum 10000), `log_backup_count` (default 3).
* **Why:** before this, errors went only to the console or the HUD log and were lost on exit; a crash left no evidence.
* **Compatibility:** standard-library `logging` only, Python 3.8-safe (lint clean). If the log folder is not writable Lily keeps running and warnings go to the console. Never raises.
* **Test command:** `py -m unittest tests.test_11_logging_version_status -v`. Manual: `py Lily.py --console`, type `who are you`, `quit`, then `type logs\lily.log`.
* **Expected result:** tests pass; the log shows a `Lily 1.1.0 starting (mode=console)` line, then `Lily stopped (mode=console)`.

### 2. Version information
* **Changed files:** new `lily_version.py` (the only place the number is defined); `Lily.py` (`--version`); shown by `--status`, the self-test header, the log start-up line and the GUI start-up log.
* **What:** `py Lily.py --version` prints three lines (`Lily 1.1.0`, the build name, Python + OS) and exits without loading any assistant code or creating any file. A test fails if any module hard-codes a different number or if this changelog stops mentioning the current version.
* **Test command:** `py Lily.py --version`
* **Expected result:** `Lily 1.1.0` on the first line.

### 3. Health / status reporting
* **Changed files:** new `lily_status.py`; `Lily.py` (`--status`); `extra_commands.py` (typed `status`); `lily_gui.py` (registers tool counts); `safe_json.py` (new thread-local read-only mode); `selftest.py`.
* **What:** `py Lily.py --status` — or typing `status`, `health check` or `Lily status` into Lily — prints: overall health (OK/DEGRADED and why), session (running / not running / **did not shut down cleanly**, with PID, start time and **uptime** for a running session), model (llama.cpp and GGUF found, size, context, template — without loading it), voice (input mode wake word / push to talk / manual / disabled; speech output, microphone libraries, recognition backend, wake word), tool/action/plugin counts, memory file health, log file size and the number of ERROR/CRITICAL lines in the last 24 h.
* **Read-only guarantee:** status never starts the model or the microphone and never repairs, moves or writes any data/config file (a damaged file is reported as damaged). A test with a deliberately damaged config proves it.
* **Uptime:** a running Lily records its start in `logs\status.json` (written at start and shutdown only — no polling). A record whose process no longer exists is reported as an unclean shutdown, not as a fake uptime. On Windows the process check uses `tasklist`; `os.kill` is never used there (it terminates the process).
* **Why:** a quick answer to "is Lily healthy, and what is she using?" without running the full self-test.
* **Test command:** `py Lily.py --status`
* **Expected result:** a short report ending with your Python/OS line; exit code 0. Without a running Lily, Session says no session recorded / not running.

### Tests actually run (author's sandbox: Python 3.12 on Linux, fake llama-cli / audio / TTS)
| Check | Result |
|---|---|
| New tests `tests/test_11_logging_version_status.py` | **54 tests, all passed** |
| Existing 164 regression tests, re-run after the changes | **all passed** |
| Full suite (`py -m unittest discover -s tests -t . -v`) | **218 tests, 0 failures** |
| Python 3.8 static lint (`tools/check_py38.py`) | no problems |
| Whole suite from a fresh extraction of the new ZIP | passed |
Bugs the new tests caught *during this work* and were fixed: `--version` was reflowed onto one line by argparse; collecting status with the plugin hub could have repaired a damaged config file (fixed with a thread-local read-only mode); the tasklist decoding assumed a Windows-only codec.

### Still requires YOUR Windows 7 machine (not verified; do not treat as proven)
* Writing and rotating `logs\lily.log` on your disk (including with antivirus active, and with two Lily windows open — Windows may refuse to rotate a file another process holds; Lily then keeps logging without rotating).
* The real `tasklist` branch of the process check (only simulated here) and crash detection after ending Lily from Task Manager.
* `status` from a second Command Prompt while the GUI is running (uptime and PID).
* Speed of `--status` on the slow CPU (it loads the plugin modules to count them).
* Non-ASCII characters in log lines (the file is UTF-8; open it in Notepad to confirm).

### Known limitations of this update
* Logs never contain your messages, so a conversation problem cannot be replayed from the log; DEBUG adds prompt *sizes* only.
* `uptime` exists only for sessions started through `Lily.py` (not for modules launched directly), and two simultaneous instances share one status record (the newest wins).
* Status shows no CPU/RAM figures (kept light on purpose; the existing `system info`/`cpu info` tools cover that).
* There is no log viewer in the HUD; use Notepad or `type logs\lily.log`.

---

Scope: Parts 1–6 of the engineering task. The VPN is untouched and out of scope.
Environment of the author's testing: **Python 3.12 on Linux with fake llama-cli / audio / TTS.** Nothing was run on Windows 7. Labels: VERIFIED (automated test passes in that sandbox), INFERRED (reasoned), **WIN7** (needs your machine).

Run the whole suite:  `py -m unittest discover -s tests -t . -v`   (or double-click `run_tests.bat`)
Expected: `Ran 218 tests … OK` (one test is skipped on Windows by design: the `ps`-based process check). Run the health check: `py Lily.py --selftest` (or `run_selftest.bat`).

---

## 1. Final architecture summary
See `docs/PART5_ARCHITECTURE_REVIEW.md` §1. In one line: the original structure was preserved; the weak points were replaced by small modules (`safe_json`, `lily_paths`, `lily_config`, `identity`, `prompt_manager`, `conversation_manager`, `safety`, `system_actions`, `system_tools`, `extra_commands`, `audio_input`, `lily_dispatch`, `selftest`) and the engine, voice, wake, action-runner and GUI-glue code were rewritten behind the same public names.

## 2. Bug fixes implemented

| # | Bug (from the audit) | Fix | Status |
|---|---|---|---|
| 1 | "As an AI assistant…" — persona was one sentence, no user name, no memory; only four exact phrases answered | identity-first system block with user name, memory summary and "never claim to be Qwen/ChatGPT"; clause-based identity matching ("Hi, who are you?", "are you Qwen?", compound name questions); names from config; output guard | VERIFIED (fake model) · real model **WIN7** |
| 2 | Persona lost when the prompt outgrew the 2048-token context (history cut by *lines*, mid-answer) | whole-turn history trimmed to a token budget; optional prompt sections dropped before identity | VERIFIED (a 70-turn test with a context-truncating fake; a negative control proves the old style *does* lose it) |
| 3 | Style/learning blocks duplicated; persona text placed outside any role block | one system block, de-duplicated learning text | VERIFIED |
| 4 | Memory wiped by one bad load + one save | quarantine (never delete) → restore from `.bak` and/or salvage complete entries → merge | VERIFIED (truncated, empty, wrong type, invalid UTF-8, garbage) |
| 5 | Non-atomic saves; no locking; relative paths | temp-file + `os.replace`, `.bak`, per-file locks, project-anchored paths | VERIFIED (failed replace, concurrent writers, other working directory) |
| 6 | `state.json`/`goals.json` damage crashed start-up; `complete_goal` never saved; config setters wiped `api_keys.json`; fallback name "JARVIS" | safe loaders, goal save, atomic config writes, fallback "Lily" | VERIFIED |
| 7 | `import pyttsx3` crashed the whole assistant when missing; engine shared across threads | guarded import; one TTS worker with a queue, COM init, failure → text mode | VERIFIED (fake) · real SAPI **WIN7** |
| 8 | `listen()` returned `None` unless device 9 was a Realtek mic; long saved names never matched truncated driver names | name matching (exact/contains/truncated), then settings hints, then the system default; sample-rate fallback | VERIFIED |
| 9 | Speech recognition was Google-only and failure text was unclear | optional offline Vosk backend, clear offline message, never raises | VERIFIED (fake) · Vosk **WIN7** |
| 10 | Wake word fired ~10× per phrase; duplicate capture threads possible; saved "enabled" did nothing after restart; mic death silent; unpinned `pip install` | cooldown + model reset, generation-safe threads, auto-start, retry-then-degrade, pinned installer | VERIFIED (fake model/PyAudio) · real **WIN7** |
| 11 | Engine: error text always "couldn't start engine"; no kill on exit; Interrupt did nothing; stdin inherited; machine paths in code | typed errors, tracked process, `atexit`/shutdown kill, real Interrupt, `stdin=DEVNULL`, `-no-cnv` auto-retry | VERIFIED (fake) · real llama-cli **WIN7** |
| 12 | GUI kept only the first line of multi-line answers; voice command silently dropped when busy; busy-flag race | `extract_answer`, visible "still working" message, locked flag | VERIFIED (logic) · GUI **WIN7** |
| 13 | Confirmation: no expiry, "sure"/"yes but wait" accepted, remote/voice could confirm | single `SafetyGate`: strict words, 60 s expiry, single use, local-only (voice needs "confirm"), unrelated message cancels | VERIFIED |
| 14 | Delete had no protection and was permanent; shutdown instant | protected paths, Recycle Bin, 30 s shutdown with "cancel shutdown" | VERIFIED |
| 15 | No timeout/validation in actions; `SystemExit` escaped | `safe_call`: timeout, required-parameter check, contained `SystemExit` | VERIFIED |
| 16 | Wifi toggle used Windows-8 cmdlets and reported success | probes for the cmdlet; otherwise an honest error | VERIFIED (source) · **WIN7** |
| 17 | Chat text like "message my brother hi" fired actions; `computer_settings` got only the tail ("40") | tighter prefixes; whole phrase passed | VERIFIED |
| 18 | `launch_program`: hard-coded user folder for Chrome; `shell=True` accepted `&`/`|` | any-user Chrome lookup; shell metacharacters refused | VERIFIED |
| 19 | `write_text_file` overwrote silently | protected-path check + timestamped backup | VERIFIED |
| 20 | `dashboard/server.py` used `removeprefix` (Python 3.9) → every request fails on 3.8; silent firewall edit | `_bearer_token` helper; firewall change is opt-in | VERIFIED (lint) |
| 21 | Hard-coded paths/usernames/device index; "Master" in messages | removed; names from config | VERIFIED (scan) |

## 3. New features implemented
* `py Lily.py --selftest [--quick] [--audio]` → PASS / WARNING / FAIL / SKIPPED per component; exit code 1 only on FAIL.
* Input modes: wake / push-to-talk / manual / disabled (`voice_input_enabled`); wake word is optional.
* Desktop commands: *list processes / what's running*, *close/kill/force close <app>* (confirmation; never system processes or Lily), *open <website>*, *cancel shutdown*.
* Action enable/disable (`save_action_enabled`), per-tool safety tier shown in the tool list.
* Settings: see `docs/PART5_ARCHITECTURE_REVIEW.md` §5.
* Tools: `tools/check_py38.py` (Python 3.8 lint), `run_selftest.bat`, `run_tests.bat`, `run_py38_check.bat`.

## 4. Files
**New:** `lily_paths.py` `safe_json.py` `lily_config.py` `identity.py` `prompt_manager.py` `conversation_manager.py` `safety.py` `system_actions.py` `system_tools.py` `extra_commands.py` `audio_input.py` `lily_dispatch.py` `selftest.py` `core/safe_call.py` `tools/check_py38.py` `requirements-optional.txt` `run_selftest.bat` `run_tests.bat` `run_py38_check.bat` `docs/*` `tests/*` (10 test modules + a fake llama-cli).
**Rewritten (same public API):** `core/local_engine.py` `voice_manager.py` `lily_audio.py` `Lily.py` `learning_manager.py` `state_manager.py` `goal_manager.py`.
**Edited:** `lily_runtime.py` (imports, prompt builders, signature `process_text(text, origin="local")`, gate, identity, desktop commands, chat path) · `lily_gui.py` · `lily_action_hub.py` · `memory_manager.py` · `memory/config_manager.py` · `core/action_loader.py` · `core/plugin_loader.py` · `core/wake_word.py` · `actions/computer_settings.py` · `advanced_tools.py` · `computer_manager.py` · `dashboard/server.py` · `voice_assistant.py` · `mic_level_test.py` · `test_microphone.py` · `INSTALL-WIN7.md` · `config/local_settings.json` (added `mic_name_hints`).
**Untouched (byte-identical to your upload):** `memory.json`, `learning.json`, `state.json`, `goals.json`, `config/api_keys.json`, `backups/`, `original_sources/`, `reference_archives/`.

## 5. Dependency changes
No new *required* package. New optional file `requirements-optional.txt` (pinned `onnxruntime==1.10.0`, `openwakeword==0.5.1`; commented `vosk`, `cryptography<43`). Advice (not enforced): `Pillow<10`, `pydantic<2` if you use the dashboard, `duckduckgo_search<7` instead of `ddgs` on Python 3.8, install PyQt5 5.15.x for the GUI. Details and per-package Win 7 notes: Part 5 review §4.

## 6. Self-test commands
```
py Lily.py --selftest            full check including a live model call (a few seconds to a minute)
py Lily.py --selftest --quick    no live model call
py Lily.py --selftest --audio    also opens the microphone and speaks a phrase
py Lily.py --version             show the version
py Lily.py --status              quick, read-only health report
py -m unittest discover -s tests -t . -v
py tools\check_py38.py
```
Expected for a healthy machine: no `[FAIL]`; WARNING lines only for things you have not installed (offline speech model, etc.). The self-test never edits your `memory.json`.

## 7. Windows 7 test procedure
`docs/WINDOWS7_TEST_PROCEDURE.md`.

## 8. Known limitations
* Not run on Windows 7, a real llama.cpp, a real microphone, SAPI voice, PyQt5 or openwakeword by the author. The suite uses fakes that reproduce the failure modes, so it proves the *logic*.
* The model is still loaded for every reply (slow on a small CPU); a resident server is proposed, not built.
* A timed-out plugin is abandoned, not killed (Python cannot kill a thread).
* `redirect_stdout` capture in the dispatcher is process-wide.
* A 0.5 B model can ignore the persona; identity questions are answered directly and replies are guarded, but free-form chat quality is the model's.
* Offline speech recognition (Vosk) is wired in but untested; until configured, voice input uses Google online.
* `core/audio_devices.py` (the UI device picker) still needs `sounddevice`.
* Playwright-based actions cannot work on Windows 7.
* The GUI itself (PyQt5 HUD) was only checked at source level.

## 9. Remaining risks
Listed with probability/impact/prevention in Part 5 review §6. The three that most need your Windows 7 result: real `llama-cli` behaviour with your build (`-no-cnv`, banner text), pyttsx3 on a worker thread, and the real model's identity behaviour.
