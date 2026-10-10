# Windows 7 test procedure

Do these in order on the real machine. Each step says what you should see. Copy any unexpected output (the text, not a description) and send it back — that is how the remaining items get closed. Steps marked **(WIN7)** are the ones nobody has verified yet.

Open a Command Prompt in the Lily folder: `cd /d C:\path\to\Lily-MARK-LIV-Local-Win7`

**1. Python and layout** — `py -3.8 --version` → `Python 3.8.x`. Your settings file keeps its own paths; nothing else needs editing.

**2. Optional packages (WIN7)** — install only what you want, one at a time, and note any that fail:
`py -m pip install -r requirements-win7.txt`, then `py -m pip install -r requirements-optional.txt` for the wake word. If you use the dashboard: `py -m pip install "pydantic<2"`.

**3. Run the self-test without the model** — `py Lily.py --selftest --quick`
Expect: no `[FAIL]`. `[WARNING]` for anything not installed is normal. If `[FAIL] Local model` appears, the paths in `config\local_settings.json` are wrong (the message says which).

**4. Real llama.cpp (WIN7)** — `py Lily.py --selftest` (full).
Expect `[PASS] Local model - answered in …s`. If it says `[FAIL] … engine error`, send the whole line: the exit code and last stderr lines are included. If the reply is empty or contains menu text, try setting `"no_conversation_flag": "off"` (or `"on"`) in `config\local_settings.json` and repeat. Note the seconds-per-reply.

**5. Identity with the real model (WIN7)** — in the same output look for `Model identity`.
`[PASS]` = the model said Lily by itself. `[WARNING]` = it didn't; identity questions are still answered directly. Then try `py Lily.py --console` and ask: `Who are you?`, `Hi, who are you?`, `What is my name?`, `Tell me about the planets`, then a few more turns. Lily should always say she is Lily; Qwen/Alibaba must never appear.

**6. Speech output (WIN7)** — `py Lily.py --selftest --quick --audio`. Expect to hear "Lily self test." If `[WARNING] Speech output` appears, send the line; text mode is unaffected.

**7. Microphone (WIN7)** — `py mic_level_test.py` lists devices. Speak when asked. `RESULT: AUDIO DETECTED` is good. To test a specific one: `py mic_level_test.py 3` or `py mic_level_test.py usb`. Then `py Lily.py --selftest --quick --audio` should show `[PASS] Microphone … opened and read it successfully`.

**8. The GUI (WIN7)** — `run_lily.bat`. Check: the window opens; the log shows "Local AI engine found", "Speech output: ready/unavailable", "Voice input mode"; type `Who are you?`; type a multi-line question (e.g. "give me three tips") and confirm the whole reply shows and is spoken; press Interrupt while it is thinking.

**9. Voice and wake word (WIN7)** — click the microphone button and say a command (needs internet unless an offline model is set up). If openwakeword is installed: enable the wake word and say "Hey Jarvis" — you should get **one** listening turn per phrase. Watch CPU in Task Manager while it is on and idle, and tell me the percentage. Switch it off again and confirm CPU returns to normal.

**10. Safety (WIN7)** — make a throwaway file `C:\Lily-test\x.txt`. Say `delete C:\Lily-test\x.txt` (if Lily does not recognise the path, tell me the exact sentence you used) → Lily asks; reply `sure` → nothing is deleted; ask again, reply `yes` → it goes to the Recycle Bin. Say `delete C:\` → refused. Say `shut down my computer`, reply `yes` → Windows shows a countdown (30 s); say `cancel shutdown` → cancelled. **Do this one with unsaved work closed.**

**11. Desktop commands (WIN7)** — `list processes`; open Notepad then `close notepad` → confirm → it closes (or asks you to save first, because Lily never force-closes unless you say "force close"); `open example.com` opens the browser.

**12. Run the automated suite** — `run_tests.bat`. Most tests use fakes and should pass; send the end of the output if any fail. Failures on Windows can be either a real problem or a test that assumed Linux; either way I need the text.

**13. Shutdown hygiene** — after closing Lily, open Task Manager → no `llama-cli.exe` or `python.exe` left running.

What to send back: the full output of steps 3–5, any WARNING/FAIL lines from 6–7, the CPU numbers from 9, and anything unexpected.
