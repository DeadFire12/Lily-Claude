from __future__ import annotations

"""Text-to-speech and speech recognition for Lily.

Everything here is OPTIONAL: if pyttsx3, SpeechRecognition or the microphone are
missing or failing, Lily keeps working in text mode (the module still imports).

Audit findings fixed:
  * `import pyttsx3` at module level crashed lily_runtime (and therefore the whole
    assistant, console included) when pyttsx3 was missing;
  * the pyttsx3 engine was created on whichever GUI thread spoke first and shared
    across threads; it now lives on ONE worker thread with a queue;
  * microphone choice depended on a hard-coded index (see audio_input.py);
  * recognition was Google-only; an offline Vosk backend is now supported;
  * every failure is reported without raising.

Speech-recognition LANGUAGE (what Lily listens for) is chosen in the HUD's Speech language
panel and saved as ``stt_language`` (see stt_languages.py). recognize() is the one place where
audio becomes text - normal listening, push-to-talk and the command that follows a wake word all
end up here - so every entry point uses the selected language. That setting is independent of
the AI mode (LOCAL/API/AUTO) and of the text-to-speech voice.
"""

import os
import queue
import re
import subprocess
import sys
import threading
import time
from typing import Optional

import audio_input
import lily_config
import lily_log
import stt_languages

_vlog = lily_log.get_logger("voice")

# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------
try:
    import pyttsx3 as _pyttsx3
    TTS_IMPORT_ERROR = ""
except Exception as _exc:  # missing package or broken COM/SAPI install
    _pyttsx3 = None
    TTS_IMPORT_ERROR = repr(_exc)

try:
    import pyaudiowpatch as pyaudio
    sys.modules["pyaudio"] = pyaudio
    import speech_recognition as sr
    AUDIO_AVAILABLE = True
    AUDIO_IMPORT_ERROR = ""
except Exception as _exc:
    sr = None
    AUDIO_AVAILABLE = False
    AUDIO_IMPORT_ERROR = repr(_exc)

last_error = ""   # human-readable reason for the most recent voice failure


def _log(*parts):
    try:
        _vlog.warning(" ".join(str(p) for p in parts))
    except Exception:
        pass
    try:
        print(*parts, file=sys.stderr)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Text-to-speech
# ---------------------------------------------------------------------------
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D\u20E3]")


def clean_for_speech(text: str, max_chars: Optional[int] = None) -> str:
    """Remove emoji/markdown and cap the length so speech stays natural and short."""
    t = _EMOJI.sub("", str(text or ""))
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"[*_`#>~|]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    limit = int(max_chars or lily_config.get_number("tts_max_chars", 500))
    if len(t) > limit:
        cut = max(t.rfind(". ", 0, limit), t.rfind("! ", 0, limit), t.rfind("? ", 0, limit))
        t = t[: cut + 1] if cut > limit // 3 else t[:limit].rstrip()
    return t


def _com_init():
    """SAPI5 (via comtypes/pywin32) needs COM initialised on the thread that uses it."""
    for modname in ("pythoncom", "comtypes"):
        try:
            mod = __import__(modname)
            fn = getattr(mod, "CoInitialize", None)
            if fn:
                fn()
                return
        except Exception:
            continue


def _uses_isolated_tts_process():
    """Use a fresh SAPI/COM process for each utterance on real Windows installations.

    The Windows 7 hardware test found that pyttsx3 returned successfully for repeated
    utterances in one process, while only the first utterance was audible. Unit tests use
    fake pyttsx3 modules and retain the in-process backend unless this helper is mocked.
    """
    return (sys.platform == "win32" and _pyttsx3 is not None
            and getattr(_pyttsx3, "__name__", None) == "pyttsx3")


class _TTSWorker(object):
    MAX_FAILURES = 3

    def __init__(self):
        self._q = queue.Queue()
        self._thread = None
        self._engine = None
        self._failures = 0
        self.disabled_reason = ""
        self._start_lock = threading.Lock()
        self._helper_lock = threading.RLock()
        self._helper_process = None
        self._cancelled_helper_pids = set()
        self.speaking = False

    @property
    def engine(self):
        # In isolated Windows mode the SAPI engine exists only inside tts_helper.py.
        return self._engine

    def _ensure_thread(self):
        with self._start_lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="lily-tts", daemon=True)
                self._thread.start()

    def _make_engine(self):
        eng = _pyttsx3.init()
        eng.setProperty("rate", int(lily_config.get_number("tts_rate", 175)))
        eng.setProperty("volume", float(lily_config.get_number("tts_volume", 1.0)))
        return eng

    def _speak_in_helper(self, text, timeout):
        """Speak in a short-lived process, giving each Windows SAPI session a fresh COM state."""
        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_helper.py")
        if not os.path.isfile(helper):
            raise RuntimeError("TTS helper file is missing: %s" % helper)

        rate = int(lily_config.get_number("tts_rate", 175))
        volume = float(lily_config.get_number("tts_volume", 1.0))
        python_exe = sys.executable
        # A caller launched with pythonw.exe may have no usable standard streams. Prefer its
        # sibling console interpreter for the helper so stdin/stdout pipes remain functional.
        if os.name == "nt" and os.path.basename(python_exe).lower() == "pythonw.exe":
            candidate = os.path.join(os.path.dirname(python_exe), "python.exe")
            if os.path.isfile(candidate):
                python_exe = candidate
        command = [python_exe, helper, "--rate", str(rate), "--volume", str(volume)]
        child_env = os.environ.copy()
        # Match the UTF-8 encoding used by communicate() on the parent side, including
        # non-ASCII names and speech. The helper never logs or prints the speech text.
        child_env["PYTHONIOENCODING"] = "utf-8"
        kwargs = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
            "cwd": os.path.dirname(helper),
            "env": child_env,
            "universal_newlines": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        # Do not flash a console window for each spoken response on the Windows GUI.
        if os.name == "nt" and hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
            kwargs["startupinfo"] = startupinfo

        process = subprocess.Popen(command, **kwargs)
        with self._helper_lock:
            self._helper_process = process

        timed_out = False
        try:
            try:
                _stdout, stderr = process.communicate(text, timeout=max(1.0, float(timeout)))
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    process.kill()
                except Exception:
                    pass
                try:
                    _stdout, stderr = process.communicate(timeout=5.0)
                except Exception:
                    stderr = ""

            with self._helper_lock:
                cancelled = process.pid in self._cancelled_helper_pids
                self._cancelled_helper_pids.discard(process.pid)
                if self._helper_process is process:
                    self._helper_process = None

            if cancelled:
                return False
            if timed_out:
                raise RuntimeError("TTS helper exceeded the %.1f second timeout" % float(timeout))
            if process.returncode != 0:
                # Keep useful failure context without ever writing the spoken content to logs.
                detail = (stderr or "").replace(text, "[speech text redacted]").strip()
                if len(detail) > 600:
                    detail = detail[-600:]
                raise RuntimeError("TTS helper exited with code %s%s" % (
                    process.returncode, (": " + detail) if detail else ""))
            return True
        finally:
            with self._helper_lock:
                if self._helper_process is process:
                    self._helper_process = None

    def _run(self):
        # COM belongs to this thread only when using the in-process backend. In Windows
        # isolation mode, the helper initializes COM on its own main thread.
        if not _uses_isolated_tts_process():
            _com_init()
        while True:
            item = self._q.get()
            if item is None:
                break
            text, done, result, timeout = item
            try:
                self.speaking = True
                if _uses_isolated_tts_process():
                    successful = self._speak_in_helper(text, timeout)
                    if successful:
                        self._failures = 0
                    result.append(bool(successful))
                else:
                    if self._engine is None:
                        self._engine = self._make_engine()
                    self._engine.say(text)
                    self._engine.runAndWait()
                    self._failures = 0
                    result.append(True)
            except Exception as exc:
                self._failures += 1
                self._engine = None          # recreate in-process engine on the next attempt
                _log("Voice output error:", exc)
                if self._failures >= self.MAX_FAILURES:
                    self.disabled_reason = "text-to-speech failed %d times (%s)" % (self._failures, exc)
                    _log("TTS unavailable. Continuing in text mode.")
                result.append(False)
            finally:
                self.speaking = False
                done.set()
        try:
            if self._engine is not None:
                self._engine.stop()
        except Exception:
            pass

    def speak(self, text: str, block: bool, timeout: float) -> bool:
        if self.disabled_reason:
            return False
        self._ensure_thread()
        done = threading.Event()
        result = []
        self._q.put((text, done, result, timeout))
        if not block:
            return True
        # The worker kills a timed-out helper and signals the event immediately afterwards.
        if not done.wait(max(0.1, float(timeout)) + 2.0):
            _log("Voice output error: speech worker did not finish within %ds" % int(timeout))
            return False
        return bool(result and result[0])

    def stop(self):
        # Cancel queued items without leaving callers waiting on orphaned Events.
        try:
            while True:
                item = self._q.get_nowait()
                if item is not None:
                    _text, done, result, _timeout = item
                    result.append(False)
                    done.set()
        except queue.Empty:
            pass

        with self._helper_lock:
            process = self._helper_process
            if process is not None and process.poll() is None:
                self._cancelled_helper_pids.add(process.pid)
                try:
                    process.kill()
                except Exception:
                    pass

        eng = self._engine
        if eng is not None:
            try:
                eng.stop()
            except Exception:
                pass

    def shutdown(self):
        self.stop()
        t = self._thread
        if t is not None and t.is_alive():
            self._q.put(None)
            t.join(timeout=3.0)

    def reset(self):
        self._failures = 0
        self.disabled_reason = ""

_tts = _TTSWorker()


def get_engine():
    """Return the in-process pyttsx3 engine, or None for isolated Windows SAPI mode."""
    return _tts.engine


def tts_status():
    if _pyttsx3 is None:
        return {"available": False, "reason": "pyttsx3 is not installed (%s)" % TTS_IMPORT_ERROR}
    if _tts.disabled_reason:
        return {"available": False, "reason": _tts.disabled_reason}
    return {"available": True, "reason": ""}


def speak(text, block: bool = True, timeout: float = 45.0):
    """Speak text. Returns False (never raises) if speech is unavailable."""
    if not lily_config.get_bool("tts_enabled", True):
        return False
    if _pyttsx3 is None:
        return False
    cleaned = clean_for_speech(text)
    if not cleaned:
        return False
    try:
        return _tts.speak(cleaned, block, timeout)
    except Exception as exc:
        _log("Voice output error:", exc)
        return False


def stop_speaking():
    _tts.stop()


def reset_tts():
    _tts.reset()


def shutdown():
    _tts.shutdown()


# ---------------------------------------------------------------------------
# Speech recognition
# ---------------------------------------------------------------------------
_vosk_model = None
_vosk_model_path = None
_vosk_problem = ""      # why the most recent _vosk_ready() call returned None


class _Never(Exception):
    """Placeholder so `except` clauses stay valid when speech_recognition is missing/stubbed."""


def _sr_exc(name):
    cls = getattr(sr, name, None) if sr is not None else None
    return cls if isinstance(cls, type) and issubclass(cls, BaseException) else _Never


def _configured_device():
    try:
        from memory.config_manager import get_input_device
        return get_input_device() or ""
    except Exception:
        return ""


def _vosk_ready(language=None):
    """Return the unpacked Vosk model folder for ``language`` (default: the saved speech
    language), or None. The reason for a None result is left in ``_vosk_problem``.

    Each language has its own model; a model for another language is never returned."""
    global _vosk_problem
    _vosk_problem = ""
    lang = language or stt_languages.get_language()
    try:
        path, problem = stt_languages.vosk_model_for(lang)
    except Exception as exc:
        path, problem = "", "the model lookup failed (%s)" % type(exc).__name__
    if not path:
        _vosk_problem = problem
        return None
    try:
        import vosk  # noqa: F401
    except Exception:
        _vosk_problem = "the 'vosk' Python package is not installed (py -3.8 -m pip install vosk)"
        return None
    return path


def _recognize_vosk(recognizer, audio, path):
    global _vosk_model, _vosk_model_path
    import json
    import vosk
    if _vosk_model is None or _vosk_model_path != path:
        _vosk_model = vosk.Model(path)
        _vosk_model_path = path
    recognizer.vosk_model = _vosk_model          # SpeechRecognition reuses this attribute
    result = recognizer.recognize_vosk(audio)
    return str(json.loads(result).get("text", "")).strip()


def _offline_hint_safe(language=None):
    """Short 'no offline model for <language>' sentence for error messages ('' if none/English)."""
    try:
        return stt_languages.offline_hint(language or stt_languages.get_language())
    except Exception:
        return ""


_DISABLED_MESSAGE = "speech recognition is disabled (stt_backend = none)"

_SECRET_PAIR = re.compile(r"(?i)([\w-]*(?:key|token|secret|password|passwd|auth|signature))=[^\s&;,)\"']+")
_BEARER = re.compile(r"(?i)\bbearer\s+\S+")


def _safe_detail(exc, limit=200):
    """One-line, length-limited text of an exception for last_error / the GUI.

    Best effort: values of key=/token=/secret=/password=/auth=/signature= pairs and 'Bearer ...' are
    replaced by <hidden> so a request URL inside an error message cannot leak a credential."""
    try:
        text = str(exc)
    except Exception:
        text = ""
    text = " ".join(text.split())
    text = _SECRET_PAIR.sub(lambda m: m.group(1) + "=<hidden>", text)
    text = _BEARER.sub("Bearer <hidden>", text)
    if len(text) > limit:
        text = text[:limit - 3] + "..."
    return text or "no details"


def _vosk_failure_text(language, path, exc):
    """Same wording for a Vosk model that cannot load/run, in the vosk and the auto branch."""
    return ("offline Vosk could not load or run the %s model in %s (%s: %s). The folder has the expected "
            "layout but may be incomplete, damaged or not compatible with the installed Vosk package."
            % (stt_languages.info(language).english_name, path, type(exc).__name__, _safe_detail(exc)))


def _recognition_blocked():
    """Why recognition must not start ('' if it may): stt_backend = none, or an unsupported value.
    Checked before the microphone is opened."""
    backend, problem = stt_languages.backend_setting()
    if problem:
        return problem
    return _DISABLED_MESSAGE if backend == "none" else ""


def recognize(recognizer, audio):
    """Turn recorded audio into text in the SELECTED speech language.

    Used by listen(), listen_push_to_talk() and therefore by the command that follows a
    wake word. Google first in auto mode (online, needs internet), with the offline Vosk
    model of the SAME language as fallback. Never uses another language's model."""
    global last_error
    last_error = ""

    language = stt_languages.get_language()
    google_kwargs = stt_languages.google_kwargs(language)

    backend, backend_problem = stt_languages.backend_setting()

    if backend_problem:
        last_error = backend_problem
        print("Voice input error:", last_error)
        return None

    if backend == "none":
        last_error = _DISABLED_MESSAGE
        return None

    # Explicit Google mode: never fall back to Vosk.
    if backend == "google":
        text = stt_languages.postprocess(
            language, recognizer.recognize_google(audio, **google_kwargs) or "")
        if text:
            print("Speech recognition: using Google online (%s)." % language)
            return text
        last_error = "Google returned no recognized words."
        return None

    # Explicit Vosk mode: work offline only.
    if backend == "vosk":
        vosk_path = _vosk_ready(language)
        if not vosk_path:
            last_error = stt_languages.missing_model_message(language, _vosk_problem)
            print("Voice input error:", last_error)
            return None

        try:
            raw_text = _recognize_vosk(recognizer, audio, vosk_path)
        except Exception as exc:
            # The folder passed validation (it has an 'am' subfolder) but Vosk could not load or run it:
            # incomplete/damaged model, wrong Vosk version, or too little memory.
            last_error = _vosk_failure_text(language, vosk_path, exc)
            print("Voice input error:", last_error)
            return None
        text = stt_languages.postprocess(language, raw_text or "")

        if text:
            print("Speech recognition: using offline Vosk (%s)." % language)
            return text

        last_error = "Vosk did not recognize any words."
        return None

    # AUTO mode: try online Google FIRST.
    google_error = None

    try:
        text = stt_languages.postprocess(
            language, recognizer.recognize_google(audio, **google_kwargs) or "")

        if text:
            print("Speech recognition: using Google online (%s)." % language)
            return text

    except Exception as exc:
        google_error = exc
        _log(
            "Google recognition failed; trying offline Vosk:",
            type(exc).__name__,
            _safe_detail(exc),
        )

    vosk_path = _vosk_ready(language)

    # If Vosk is not configured for THIS language, preserve Google's original error.
    if not vosk_path:
        if google_error is not None:
            raise google_error

        last_error = (
            "Google returned no words and no offline %s model is set up."
            % stt_languages.info(language).english_name
        )
        if _vosk_problem and not _vosk_problem.startswith("no "):
            last_error += " Reason: %s." % _vosk_problem
        print("Voice input error:", last_error)
        return None

    # Google failed or returned no text: try offline Vosk.
    try:
        text = stt_languages.postprocess(language, _recognize_vosk(
            recognizer, audio, vosk_path
        ) or "")

        if text:
            print("Speech recognition: using offline Vosk fallback (%s)." % language)
            return text

        if google_error is not None:
            last_error = (
                "Google recognition failed and offline Vosk "
                "returned no words."
            )
        else:
            last_error = (
                "Google returned no words and offline Vosk "
                "also returned no words."
            )

        print("Voice input error:", last_error)
        return None

    except Exception as exc:
        if google_error is not None:
            last_error = (
                "Google recognition failed (%s); %s"
                % (type(google_error).__name__, _vosk_failure_text(language, vosk_path, exc))
            )
        else:
            last_error = (
                "Google returned no words; %s" % _vosk_failure_text(language, vosk_path, exc)
            )

        print("Voice input error:", last_error)
        return None



def _capture(recognizer, mic_kwargs):
    with sr.Microphone(**mic_kwargs) as source:
        print("Lily is listening...")
        print("Please wait while I adjust the microphone...")

        # First, measure the background noise.
        recognizer.adjust_for_ambient_noise(
            source,
            duration=lily_config.get_number(
                "mic_calibration_seconds", 0.6
            )
        )

        # Configure speech detection after calibration.
        recognizer.pause_threshold = 1.0
        recognizer.non_speaking_duration = 0.5

        # Only ask the user to speak after calibration is complete.
        print("I'm ready! Speak now.")

        return recognizer.listen(
            source,
            timeout=10,
            phrase_time_limit=10
        )



def listen():
    """Record one phrase and return its text, or None. Never raises."""
    global last_error
    last_error = ""
    if not lily_config.get_bool("voice_input_enabled", True):
        last_error = "voice input is disabled in the settings"
        print("Voice input is disabled. Text mode is available.")
        return None
    blocked = _recognition_blocked()
    if blocked:
        last_error = blocked
        print("Voice input error:", last_error + ". The microphone was not opened.")
        return None
    if not AUDIO_AVAILABLE:
        last_error = "audio libraries are not installed (%s)" % AUDIO_IMPORT_ERROR
        print("Voice input unavailable: %s. Text mode remains available." % last_error)
        return None

    WaitTimeout, Unknown, RequestErr = _sr_exc("WaitTimeoutError"), _sr_exc("UnknownValueError"), _sr_exc("RequestError")
    try:
        recognizer = sr.Recognizer()
        try:
            names = list(sr.Microphone.list_microphone_names())
        except Exception:
            names = []
        wanted = _configured_device()
        hints = lily_config.get("mic_name_hints") or []
        preferred_index = lily_config.get("mic_device_index")
        index, reason = audio_input.resolve_input_index(
            names, wanted, hints, preferred_index=preferred_index)
        if reason == "configured-index":
            print("Voice input: using verified microphone index %s." % index)
        elif reason == "configured-not-found":
            print("Voice input: the saved microphone wasn't found; using the system default.")
        rates = lily_config.get("mic_sample_rates") or [None]

        audio = None
        open_error = None
        for rate in rates:
            kwargs = {"chunk_size": 1024}
            if rate:
                kwargs["sample_rate"] = int(rate)
            if index is not None:
                kwargs["device_index"] = index
            try:
                audio = _capture(recognizer, kwargs)
                open_error = None
                break
            except (WaitTimeout, Unknown, RequestErr):
                raise
            except (OSError, ValueError, AttributeError, AssertionError) as exc:
                open_error = exc       # this rate/device could not be opened: try the next rate
        if audio is None:
            last_error = "could not open the microphone (%s)" % (open_error,)
            print("Voice input error:", last_error)
            return None

        print("Lily is thinking...")
        text = recognize(recognizer, audio)
        text = (text or "").strip()
        if not text:
            if not last_error:          # keep a more specific reason recorded by recognize()
                last_error = "no words were recognised"
            return None
        return text
    except WaitTimeout:
        last_error = "you didn't start speaking in time"
        print("Voice input error: You didn't start speaking in time.")
        return None
    except Unknown:
        last_error = "audio heard but not understood"
        print("Voice input error: I heard audio, but couldn't understand the words.")
        return None
    except RequestErr as exc:
        hint = _offline_hint_safe()
        last_error = "the online speech service is unreachable (%s)" % _safe_detail(exc)
        if hint:
            last_error += " " + hint
        print("Voice input error: the online speech service isn't reachable. "
              "Voice input needs internet unless an offline model is set up. %sText mode remains available."
              % ((hint + " ") if hint else ""))
        return None
    except Exception as exc:
        last_error = "%s: %r" % (type(exc).__name__, exc)
        _vlog.exception("unexpected voice input error")
        print("Voice input error:", type(exc).__name__, repr(exc))
        return None


def listen_push_to_talk(stop_event, max_duration=15.0):
    """Record while a push-to-talk key is held, then recognize the recording.

    Unlike ``listen()``, this deliberately does not run ambient-noise calibration
    after the key is pressed: calibration would consume the beginning of the
    user's sentence. The key-down starts recording; key-up finalizes it.
    ``stop_event`` is set by the hotkey release handler.
    """
    global last_error
    last_error = ""
    if not lily_config.get_bool("voice_input_enabled", True):
        last_error = "voice input is disabled in the settings"
        print("Voice input is disabled. Text mode is available.")
        return None
    blocked = _recognition_blocked()
    if blocked:
        last_error = blocked
        print("Voice input error:", last_error + ". The microphone was not opened.")
        return None
    if not AUDIO_AVAILABLE:
        last_error = "audio libraries are not installed (%s)" % AUDIO_IMPORT_ERROR
        print("Voice input unavailable: %s. Text mode remains available." % last_error)
        return None

    WaitTimeout = _sr_exc("WaitTimeoutError")
    Unknown = _sr_exc("UnknownValueError")
    RequestErr = _sr_exc("RequestError")
    recognizer = sr.Recognizer()
    try:
        try:
            names = list(sr.Microphone.list_microphone_names())
        except Exception:
            names = []
        wanted = _configured_device()
        hints = lily_config.get("mic_name_hints") or []
        preferred_index = lily_config.get("mic_device_index")
        index, reason = audio_input.resolve_input_index(
            names, wanted, hints, preferred_index=preferred_index)
        if reason == "configured-index":
            print("Push-to-talk: using verified microphone index %s." % index)
        elif reason == "configured-not-found":
            print("Push-to-talk: saved microphone not found; trying system default.")

        rates = lily_config.get("mic_sample_rates") or [None]
        audio = None
        open_error = None
        for rate in rates:
            kwargs = {"chunk_size": 1024}
            if rate:
                kwargs["sample_rate"] = int(rate)
            if index is not None:
                kwargs["device_index"] = index
            try:
                with sr.Microphone(**kwargs) as source:
                    print("Push-to-talk recording. Speak while holding Ctrl+Space; release to send.")
                    frames = []
                    started = time.monotonic()
                    while not stop_event.is_set():
                        if time.monotonic() - started >= max(1.0, float(max_duration)):
                            print("Push-to-talk reached the %.0f-second recording limit." % max_duration)
                            break
                        chunk = source.stream.read(source.CHUNK)
                        if chunk:
                            frames.append(chunk)
                    if not frames:
                        last_error = "push-to-talk ended before audio was captured; hold Ctrl+Space while speaking"
                        print("Voice input error:", last_error)
                        return None
                    raw_audio = b"".join(frames)
                    sample_rate = int(source.SAMPLE_RATE)
                    sample_width = int(source.SAMPLE_WIDTH)
                    duration = len(raw_audio) / float(max(1, sample_width * sample_rate))
                    if duration < 0.25:
                        last_error = "push-to-talk recording was too short; hold Ctrl+Space while speaking"
                        print("Voice input error:", last_error)
                        return None
                    audio = sr.AudioData(raw_audio, sample_rate, sample_width)
                    open_error = None
                    break
            except (OSError, ValueError, AttributeError, AssertionError) as exc:
                open_error = exc
        if audio is None:
            last_error = "could not open the microphone (%s)" % (open_error,)
            print("Voice input error:", last_error)
            return None

        print("Lily is thinking...")
        text = (recognize(recognizer, audio) or "").strip()
        if not text:
            if not last_error:
                last_error = "no words were recognised"
            return None
        return text
    except WaitTimeout:
        last_error = "speech recognition timed out"
        print("Voice input error: speech recognition timed out.")
        return None
    except Unknown:
        last_error = "audio heard but not understood"
        print("Voice input error: I heard audio, but couldn't understand the words.")
        return None
    except RequestErr as exc:
        hint = _offline_hint_safe()
        last_error = "the online speech service is unreachable (%s)" % _safe_detail(exc)
        if hint:
            last_error += " " + hint
        print("Voice input error: the online speech service isn't reachable. "
              "Voice input needs internet unless an offline model is set up. %sText mode remains available."
              % ((hint + " ") if hint else ""))
        return None
    except Exception as exc:
        last_error = "%s: %r" % (type(exc).__name__, exc)
        _vlog.exception("unexpected push-to-talk input error")
        print("Voice input error:", type(exc).__name__, repr(exc))
        return None

