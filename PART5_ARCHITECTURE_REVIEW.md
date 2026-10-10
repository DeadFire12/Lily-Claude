# Lily — Part 5: Architecture, Compatibility, Resource & Error-Handling Review

Evidence labels used everywhere in these documents:

* **VERIFIED** — tested by the automated suite in a development sandbox (Python 3.12, Linux, with a *fake* llama-cli, fake audio and fake TTS). It proves the logic, not Windows 7 behaviour.
* **INFERRED** — concluded from reading code or from published facts; not executed.
* **REQUIRES WINDOWS 7 TESTING** — only your machine can confirm it. Nothing in this project has been run on Windows 7 by the author of this review.

---

## 1. Architecture as it now stands

The existing structure was kept (no rewrite). The conceptual layout maps onto the real files like this:

```
Lily
├── Core            lily_paths.py (paths) · lily_config.py (settings) · safe_json.py (atomic/recoverable files)
│                   lily_runtime.py (process_text: the decision pipeline) · state_manager.py
├── Brain           core/local_engine.py (llama.cpp process) · prompt_manager.py (prompt + token budget)
│                   identity.py (names, identity answers, output guard) · conversation_manager.py
│                   memory_manager.py · learning_manager.py · goal_manager.py · personality.py · brain.py
├── Voice           audio_input.py (device choice) · voice_manager.py (TTS worker + recognition)
│                   lily_audio.py (modes, push-to-talk, wake loop) · core/wake_word.py · core/hotkey.py
├── Actions         lily_action_hub.py · core/action_loader.py · core/plugin_loader.py · core/safe_call.py
│                   safety.py (tiers + the single confirmation gate) · system_actions.py · system_tools.py
│                   extra_commands.py · tool_registry.py + 23 Lily tools · actions/ (16) · plugins/
├── Interface       Lily.py (CLI/--selftest) · lily_gui.py + ui.py (PyQt5 HUD) · lily_dispatch.py · dashboard/
└── Diagnostics     selftest.py · tests/ (164 tests in 9 modules) · tools/check_py38.py · mic_level_test.py · test_microphone.py
```

Message flow (unchanged in shape, hardened in every stage):

```
GUI/CLI/voice/dashboard -> lily_dispatch.dispatch(text, origin)
   1. SafetyGate: answers or cancels a pending confirmation
   2. simple_route: explicit Mark-LIV commands
   3. lily_runtime.process_text -> identity -> desktop commands -> tools -> memory -> AI chat
        chat: PromptBuilder(identity first, whole turns, token budget) -> LocalEngine -> llama-cli -> GGUF
   4. identity guard on the reply -> history -> reply
```

There is no separate "agent layer": tool selection is rule-based (tool_intent_engine / simple_route) and the model is only the conversational fallback. That is a deliberate property of this build, not a defect.

---

## 2. Resource management (Part 5A)

Every background worker, what it had, and what it has now.

| Worker | Startup | Shutdown | Timeout | Exceptions | Status |
|---|---|---|---|---|---|
| llama-cli process | per call | `shutdown()` + `atexit` kill it; Interrupt kills it | `timeout` setting; child killed on expiry | typed errors (not configured / timeout / crash / interrupted) | **Fixed — VERIFIED** (fake llama) |
| TTS | one worker thread, lazy | `voice_manager.shutdown()` joins it | `speak()` waits ≤45 s | init/say failure → `False`; disabled after 3 failures | **Fixed — VERIFIED** (fake pyttsx3); real SAPI **REQUIRES WIN7 TESTING** |
| Wake detector thread | `start()` per-session queue + generation | `stop()` joins (1.5 s) | n/a | errors rate-limited; model local to thread | **Fixed — VERIFIED** |
| Wake microphone thread | per-thread stop event | `shutdown()` joins | retries 3× with backoff, then degrades | all caught; message logged | **Fixed — VERIFIED** (fake PyAudio) |
| Push-to-talk poller | on enable | `stop()` | n/a | caught, falls back to window keys | unchanged (30 Hz poll, cheap) |
| Voice-input thread | per request, lock-guarded | daemon | `listen()` 10 s + 10 s limit | caught, returns None | **Hardened — VERIFIED** |
| GUI worker thread | per message | daemon | engine timeout | caught; `_busy` reset in `finally`; busy flag now lock-protected | **Hardened** (source-checked; Qt itself **REQUIRES WIN7 TESTING**) |
| Actions / plugins | per call | n/a | 60 s default, longer for build-type actions; caller released on timeout | `Exception` and `SystemExit` contained | **Fixed — VERIFIED** (a hung thread is *abandoned*, not killed — see risks) |
| Dashboard | on `--dashboard` | daemon | n/a | firewall edit now opt-in | partly changed |

Idle cost (INFERRED, REQUIRES WIN7 TESTING): with the wake word **off** (the default) Lily has no polling loop except the optional push-to-talk key poll. With it **on**, the microphone stays open and ONNX inference runs about 12 times a second; expect a small constant CPU load on the i5-7200U. Measure it with Task Manager.

Memory: the chat history is capped at 60 turns and further trimmed per prompt to the token budget; the model is not kept resident (it is loaded per reply, see Risk 2).

---

## 3. Graceful degradation (Part 5B)

Every row below is covered by `tests/test_09_integration.py`, `test_06_voice.py` or `test_07_wake.py` and passes in the sandbox.

| If this fails | Lily does | Text mode? |
|---|---|---|
| pyttsx3 missing/broken | `TTS unavailable. Continuing in text mode.` Import no longer crashes (it used to take the whole assistant down) | yes |
| SpeechRecognition / PyAudio missing | `Voice input unavailable … Text mode remains available.` | yes |
| Microphone cannot open | tries other sample rates, then reports; never crashes | yes |
| No internet for Google STT | `Voice input needs internet unless an offline model is set up.` | yes |
| openwakeword missing / model files missing | `Wake word unavailable.` push-to-talk, manual voice and typing still work | yes |
| Wake microphone dies mid-run | 3 retries with backoff, then `Wake word unavailable. … text mode remain available.` | yes |
| llama.cpp or the GGUF missing | `My local AI model isn't set up yet … my tools still work.` Identity, memory and tools keep working | yes |
| llama.cpp hangs | killed at the timeout; `I took too long to think …` | yes |
| llama.cpp crashes | `My AI engine stopped unexpectedly.` (details to stderr) | yes |
| memory/state/goals/config file damaged | original preserved, recovered, Lily starts | yes |
| a plugin/action is broken, raises, hangs or calls `sys.exit()` | contained; Lily answers the next message | yes |
| PyQt5 missing | `Lily.py --console` still works | console |

---

## 4. Windows 7 / Python 3.8 dependency audit (Part 5C)

Derived from the real imports in the active code and `requirements-win7.txt`. Python 3.8 is the last release that supports Windows 7. **None of the "Win7" cells below were tested on Windows 7**; they are INFERRED from package metadata and published support statements, except where the user reported a result.

| Package | Spec | Purpose | Python 3.8 | Windows 7 | Required? | Replacement / note |
|---|---|---|---|---|---|---|
| PyQt5 | 5.15.x (not in requirements — install separately) | HUD | wheels exist | Qt 5.15 officially supports Win 7 — test | **Required for GUI only** | `Lily.py --console` |
| psutil | >=5.9,<6 | HUD system stats (imported at module level by ui.py) | yes | 5.x believed OK — test | Required for GUI | tasklist/wmic |
| numpy | >=1.19,<2 | wake word, avatar | resolves to ≤1.24.4 on 3.8 | prefer 1.21–1.24; test | Optional | none needed without wake word |
| pyttsx3 | >=2.9,<3 | speech output (SAPI5 via comtypes/pywin32) | yes | SAPI exists on Win 7 — test threading | Optional | VBScript/SAPI fallback (not built) |
| SpeechRecognition | >=3.10,<4 | voice input | yes | pure Python | Optional | — |
| pyaudiowpatch | >=0.2,<1 | microphone | cp38 wheels | user already uses it | Optional | PyAudio |
| openwakeword | **==0.5.1** | wake word | yes | **user-tested** | Optional | push-to-talk |
| onnxruntime | **==1.10.0** | wake word inference | yes | **user-tested** (newer builds dropped Win 7) | Optional | — |
| vosk | unpinned (`requirements-optional.txt`) | offline voice input | cp38 wheels | **untested** — needs a model folder and the VC++/UCRT runtime | Optional | Google STT (online) |
| send2trash | >=1.8,<3 | Recycle-Bin deletes | yes | ctypes/shell32 | Optional (permanent delete without it, clearly stated) | — |
| pyautogui | >=0.9,<1 | keyboard/mouse actions | yes | ctypes user32 | Optional | — |
| pyperclip | >=1.8,<2 | clipboard | yes | yes | Optional | — |
| requests | >=2.31,<3 | web actions | yes | Win 7's old TLS roots may reject sites — test | Optional | — |
| Pillow | >=8,<11 | screenshots/images | ≤10.x on 3.8 | **prefer `<10`** (9.5 is the conservative pick) | Optional | — |
| pdfplumber / PyPDF2 / openpyxl / python-docx / beautifulsoup4 | as listed | file_processor / web actions | yes | pdfplumber 0.11 pulls pypdfium2 (binary) — test | Optional | — |
| fastapi + uvicorn + python-multipart | <0.111 / <0.31 | remote dashboard | yes | **install `pydantic<2`**: pydantic 2's Rust core may not load on Win 7 | Optional | don't use `--dashboard` |
| cryptography | **<43** | dashboard encryption | yes | newer builds use a Rust toolchain that dropped Win 7 | Optional | — |
| sounddevice | unpinned | the UI's device picker only | yes | bundles PortAudio — test | Optional | pyaudiowpatch listing (not built) |
| pycaw, comtypes, pywin32, wmi, pynvml, pywinauto, pygetwindow, qrcode | unpinned | volume, stats, window control, QR | mostly | test individually | Optional | — |
| ddgs | 9.x (in a requirements comment) | web search | **needs Python ≥3.9** | — | Optional | use `duckduckgo_search<7` on 3.8 |
| playwright | 1.4x | browser/flight actions | yes | **browsers need Windows 10+** | Optional | those actions will not work on Win 7 |
| opencv-python, mss, pandas, python-pptx, pydub, youtube-transcript-api | optional accessories | screen/camera/data | yes | test | Optional | — |
| torch, faster-whisper, kokoro, edge-tts, miniaudio | — | **only imported by unused modules** (`core/stt.py`, `tts.py`, `echo.py`) | — | torch will not run on Win 7 | **Do not install** | unnecessary |

Findings from the audit that were acted on: the wake-word installer is now pinned (it used to run an unpinned `pip install openwakeword`); `dashboard/server.py` used `str.removeprefix` (Python 3.9) which would have failed **every dashboard request on Python 3.8** — fixed and covered by `tools/check_py38.py`; `core/audio_devices.py` needs `sounddevice` which was never listed; `requirements-optional.txt` now documents the optional stacks.

---

## 5. Configuration and path strategy (Part 5D)

One rule: **nothing machine-specific lives in code.** Everything that differs between computers lives in `config/local_settings.json` (or an environment variable), and the program has safe defaults.

Resolution order for engine paths: environment (`LILY_LLAMA_PATH`, `LILY_MODEL_PATH`) → `config/local_settings.json` → auto-discovery inside the project (`llama/`, `models/`) → `PATH`. Doubled backslashes such as `D:\\DEAD FIRE` are normalised.

Data location: all four data files and the config are resolved against the project folder (override with `LILY_DATA_DIR`, `LILY_CONFIG_DIR`), never the current working directory — starting Lily from a shortcut, an IDE or `pythonw` can no longer silently load an empty memory.

New settings (all optional; defaults shown in `lily_config.py`): `chat_max_tokens`, `chat_template`, `no_conversation_flag` (auto/on/off), `extra_llama_args`, `voice_input_enabled`, `tts_enabled/rate/volume`, `stt_backend` (auto/vosk/google/none), `vosk_model_path`, `mic_sample_rates`, `mic_name_hints`, `wake_threshold`, `wake_cooldown_seconds`, `wake_pip_spec`, `confirm_ttl_seconds`, `allow_remote_confirmation`, `shutdown_delay_seconds`, `dashboard_auto_firewall`.

Removed from code: the `D:\DEAD FIRE` fallback paths, `C:\Users\sedaghat\…` (Chrome launcher and the install note), the hard-coded microphone index 9 / "Realtek" name (the diagnostic scripts take an argument now), and "JARVIS" as the fallback assistant name. Your own machine's values stay in your settings file; the Realtek microphone preference was moved there as `mic_name_hints`.

---

## 6. Future-risk analysis (Part 5E)

| # | Risk | Probability | Impact | Why it may happen | Prevention (done / proposed) | Test |
|---|---|---|---|---|---|---|
| 1 | llama.cpp update changes flags or enters conversation mode | Medium | High | llama-cli changed interactive defaults across builds; your build is `2567073…` | `stdin=DEVNULL`, `-no-cnv` auto-detected with a safe retry, `extra_llama_args`/`no_conversation_flag` escape hatches | `test_02_engine` (VERIFIED with fake); **real binary: Win7 procedure step 4** |
| 2 | Slow replies: the model reloads for every message | High | Medium | one `llama-cli` process per reply, no KV reuse | not changed (a resident `llama-server` is a bigger change — Priority 3) | measure in the Win 7 procedure |
| 3 | Abandoned plugin threads accumulate | Low | Medium | Python cannot kill a thread; a timed-out handler keeps running | caller released; names visible as `lily-tool`; keep timeouts short | `test_05_plugins` |
| 4 | `redirect_stdout` is process-wide | Medium | Low | the dispatcher captures stdout while the runtime runs; other threads printing at that moment are captured | proposed: return structured results instead of printing (Priority 3) | none yet |
| 5 | pyttsx3/COM misbehaves off the main thread | Medium | Medium | SAPI5 is COM; worker now initialises COM and owns the engine | single TTS worker, COM init, failure → text mode | fake: VERIFIED; real: **Win7 step 6** |
| 6 | Newer wheels dropped Windows 7 (Rust-built: pydantic-core, cryptography ≥43, onnxruntime >1.10) | Medium | Medium | upstream build toolchains require Windows 10 | pins in `requirements-optional.txt`; `pydantic<2` advice | `test_10` checks pins; install is **Win7 step 2** |
| 7 | Antivirus/indexer locks a data file during replace | Medium | Low | Windows refuses `os.replace` on an open file | retry with back-off; failed replace leaves the old file intact | `test_04` (replace failure) |
| 8 | Disk full during a save | Low | Medium | temp file cannot be written | write-then-replace: old file untouched, temp removed | `test_04` |
| 9 | Remote dashboard exposure | Medium | High | LAN port with AES session key; remote text reaches the same runtime | remote confirmations refused by default, firewall edit opt-in; review auth before exposing beyond your LAN | `test_08` |
| 10 | Google STT fails on Win 7 | Medium | Medium | old TLS roots/ciphers, or no internet | offline Vosk backend (needs testing), clear message, text mode | `test_06` (fake) |
| 11 | Backup/corrupt copies pile up | Low | Low | every recovery keeps the original | files are small; clean manually when satisfied | — |
| 12 | Small model ignores the persona | High | Low | a 0.5 B model follows instructions loosely | identity questions answered directly; output guard rewrites foreign claims; self-test reports it | `test_03` (fake model); real: **Win7 step 5** |

---

## 7. Prioritised repair plan (Part 5F) and what was done

**Priority 1 — critical (all implemented)**
1. Memory/config/state/goals: atomic writes, `.bak`, quarantine-and-recover, merge of backup and salvage, locks, absolute paths; stop a damaged state/goals file from crashing start-up.
2. Identity: one identity-first system block, user name and a memory summary in the prompt, whole-turn history inside a token budget, direct answers to identity questions by clause matching, output guard, names from configuration.
3. Optional parts must not kill core: guarded pyttsx3/audio imports; TTS worker; STT never raises.
4. Destructive actions: one gate (strict words, 60 s expiry, local-only, single use), protected paths, Recycle Bin, shutdown with a 30 s cancel window, `write_text_file` keeps a backup, destructive Mark actions gated.

**Priority 2 — important (implemented)**
5. Local engine rewrite (typed errors, process tracking, Interrupt, timeouts, `-no-cnv` handling, no machine paths).
6. Microphone selection by name with fallbacks (configured → hints → system default), shared by listening and the wake loop; sample-rate fallback.
7. Wake word: cooldown, generation-safe threads, retry-then-degrade, auto-start from the saved setting, pinned installer.
8. Plugin/action runner: timeout, validation, `SystemExit` containment, action enable/disable.
9. Self-test (`--selftest`), regression suite, Python 3.8 lint; removed `removeprefix`, hard-coded user/device values, unguarded wifi cmdlets, `shell=True` injection in the program launcher.

**Priority 3 — useful (not done; proposed)**
10. Keep the model resident (local `llama-server`) to cut reply latency.
11. Replace stdout capture with structured results from `process_text`.
12. A SAPI-via-VBScript TTS fallback with no Python dependencies; pyaudiowpatch-based device picker so `sounddevice` is not needed.
13. Qt-level automated tests on the target machine.

**Priority 4 — optional**
14. Split `process_text` (3,000+ lines) into modules; retire the unused `lily_mark_compat/`, `core/stt.py`, `core/tts.py`, `core/echo.py`, `ai_tool_planner.py` after you confirm nothing of yours uses them.
