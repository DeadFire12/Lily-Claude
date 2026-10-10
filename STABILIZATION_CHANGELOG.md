# Lily stabilization — what changed, why, and how to check it

Scope: Parts 1–6 of the engineering task. The VPN is untouched and out of scope.
Environment of the author's testing: **Python 3.12 on Linux with fake llama-cli / audio / TTS.** Nothing was run on Windows 7. Labels: VERIFIED (automated test passes in that sandbox), INFERRED (reasoned), **WIN7** (needs your machine).

Run the whole suite:  `py -m unittest discover -s tests -t . -v`   (or double-click `run_tests.bat`)
Expected: `Ran 164 tests … OK` (one test is skipped on Windows by design: the `ps`-based process check). Run the health check: `py Lily.py --selftest` (or `run_selftest.bat`).

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
**New:** `lily_paths.py` `safe_json.py` `lily_config.py` `identity.py` `prompt_manager.py` `conversation_manager.py` `safety.py` `system_actions.py` `system_tools.py` `extra_commands.py` `audio_input.py` `lily_dispatch.py` `selftest.py` `core/safe_call.py` `tools/check_py38.py` `requirements-optional.txt` `run_selftest.bat` `run_tests.bat` `run_py38_check.bat` `docs/*` `tests/*` (9 test modules + a fake llama-cli).
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
