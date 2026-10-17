"""Importable runtime extracted from Kiyoto's working Lily CLI.

The large conversation/tool/memory logic is kept local here so the GUI can call
the same brain without running a second copy of Lily.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime


from intent_engine import understand


from personality import get_personality_prompt



from memory_manager import (

    load_memory,

    save_memory,

    remember,

    find_memory,

    forget_memory,

    forget_all,

    get_memories_by_category

)



from context_engine import (

    set_context,

    clear_context,

    get_context,

    has_context

)


# =========================================
# NEW AGENT SYSTEMS
# =========================================


from state_manager import (

    load_state,

    set_state,

    get_state,

    get_all_state

)



from goal_manager import (

    load_goals,

    save_goals,

    add_goal,

    complete_goal,

    get_goals

)



from brain import (

    think

)



from learning_manager import (

    load_learning,

    save_learning,

    learn,

    find_learning,

    get_all_learning

)


from backup_manager import (
    
    create_backup,
    
    list_backups
    
)


from tool_registry import (
    
    create_tool_manager
    
)


from tool_intent_engine import (
    
    understand_tool
    
)


from tool_chain import (
    
    ToolChain
    
)


from computer_manager import (
    
    get_system_info,
    
    get_cpu_info,
    
    get_memory_info,
    
    get_disk_info,
    
    get_computer_status,
    
    get_battery_info,
    
    get_network_info,
    
    get_user_info,
    
    get_datetime_info,
    
    launch_program,
    
    take_screenshot
    
)


from voice_manager import (
    
    speak,
    
    listen
)


from voice_assistant import (
    
    VoiceAssistant
    
)


from plugin_manager import (
    
    PluginManager
    
)


from file_manager import (
    list_files,
    search_files
)


# =========================================================
# CONFIGURATION
# =========================================================

from core.local_engine import get_settings, available as local_engine_available, generate as local_generate
from core.local_engine import (EngineNotConfigured, EngineTimeout, EngineCrash, EngineInterrupted,
                               trim_incomplete_sentence)
from core import ai_router
import identity
import lily_log
import prompt_manager
import safety
import system_actions
import extra_commands
from conversation_manager import Conversation

_log = lily_log.get_logger("runtime")

_LOCAL_SETTINGS = get_settings()
LLAMA = _LOCAL_SETTINGS["llama_path"]
MODEL = _LOCAL_SETTINGS["model_path"]

MEMORY_FILE = "memory.json"


# =========================================================
# TIME
# =========================================================

def now():

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# =========================================================
# YES / NO
# =========================================================

def is_yes(text):
    
    text = text.lower().strip()

    yes_words = [

        "yes",
        "yeah",
        "yep",
        "yup",
        "yea",
        "sure",
        "correct",
        "right",
        "exactly",
        "that's right",
        "thats right"
    ]

    for word in yes_words:

        if (
            text == word
            or text.startswith(word + " ")
            or text.startswith(word + ",")
            or text.startswith(word + ".")
            or text.startswith(word + "!")
        ):
            return True

    return False



def is_no(text):
    
    text = text.lower().strip()

    no_words = [

        "no",
        "nope",
        "nah",
        "incorrect",
        "wrong",
        "not anymore",
        "that's wrong",
        "thats wrong"
    ]

    for word in no_words:

        if (
            text == word
            or text.startswith(word + " ")
            or text.startswith(word + ",")
            or text.startswith(word + ".")
            or text.startswith(word + "!")
        ):
            return True

    return False



# =========================================================
# MEMORY STATE
# =========================================================

memory = load_memory()

state = load_state()

goals = load_goals()

learning = load_learning()


# =========================================================
# AGENT SYSTEMS
# =========================================================

tool_manager = create_tool_manager()


tool_chain = ToolChain(
    
    tool_manager
    
)


voice_assistant = VoiceAssistant(
    
    listen,
    
    speak
    
)


plugin_manager = PluginManager(
    os.path.join(
        os.path.dirname(
            os.path.abspath(__file__)
        ),
        "plugins"
    )
)

plugin_manager.load_plugins()


#==========================================================


pending_key = None

pending_value = None

waiting_memory_confirmation = False

waiting_new_value = False

waiting_clear_confirmation = False

pending_tool_confirmation = None


# =========================================================
# AI CONFIG
# =========================================================

def build_learning_prompt():
    """Learned information about the user (de-duplicated; see prompt_manager)."""
    return prompt_manager.build_learning_text(learning)


def build_system_prompt():
    """Compatibility wrapper: the identity-first system block (ChatML).

    The real chat path assembles its prompt in prompt_manager.build_chat_prompt
    so the persona can never be pushed out of the model's context window."""
    assistant_name, user_name = identity.get_names(memory)
    sections = prompt_manager.build_system_sections(
        assistant_name, user_name, get_personality_prompt(), "",
        build_learning_prompt(), prompt_manager.summarize_memory(memory))
    profile = prompt_manager.get_profile(get_settings()["chat_template"])
    return profile["system"].format(content="\n\n".join(t for _n, t, _r in sections) + "\n")


conversation = Conversation()
_origin = "local"   # who sent the message being processed: local | voice | remote


# =========================================================
# MAIN LOOP
# =========================================================



def _clear_all_memories():
    """Runs ONLY after the safety gate has received a valid confirmation."""
    amount = len(memory)
    forget_all(memory)
    return ("Done. I forgot all %d memories. "
            "A safety copy of memory.json was kept next to it." % amount)


def process_text(user_text, origin="local"):
    """Process exactly one user message using the original Lily logic.

    origin is "local" (typed on this computer), "voice" or "remote" (dashboard);
    the safety gate uses it to decide who may confirm a destructive action."""
    global conversation, pending_key, pending_value, waiting_memory_confirmation, waiting_new_value, waiting_clear_confirmation, pending_tool_confirmation, _origin
    _origin = origin or "local"
    
    user = user_text
    
    
    if not user:
    
        return {"output": ""}
    
    
    lower = user.lower()
    
    # =========================================================
    # VOICE INPUT
    # =========================================================
    
    if lower == "voice mode":
    
        print("Lily: Voice mode activated. ЁЯОЩя╕ПтЭдя╕П")
    
        spoken_text = listen()
    
        if spoken_text:
    
            print("You:", spoken_text)
    
            user = spoken_text.strip()
            lower = user.lower()
            _origin = "voice"
    
        else:
    
            print("Lily: I couldn't understand you.")
    
            return {"output": ""}
    
    
    # =====================================================
    # SAFETY GATE FIRST
    # A pending destructive confirmation is answered here - or cancelled by any unrelated message -
    # BEFORE any legacy yes/no flow below can see the text. Strict words only, 60 s expiry, single
    # use, and the message origin (typed / voice / remote) decides who may confirm. See safety.py.
    # =====================================================

    consumed, gate_message = safety.get_gate().handle_reply(user, origin=_origin)

    if consumed:
        print("Lily:", gate_message)
        return {"output": gate_message}

    # =====================================================
    # EXIT

    # =====================================================
    
    if lower in [
        "exit",
        "quit",
        "bye"
    ]:
    
        _bye_user = identity.get_names(memory)[1]
        print(
            "Lily: Goodbye" + (", " + _bye_user if _bye_user else "") + "! тЭдя╕П"
        )
    
        return {"output": "", "exit": True}
    
    
    
    # =====================================================
    # LEARNING TEST
    # =====================================================
    
    if lower.startswith("learn that "):
    
        statement = user[
            len("learn that "):
        ].strip()
    
    
        learn(
            learning,
            statement,
            statement
        )
    
    
        print(
            f"Lily: I'll learn that: {statement}. ЁЯзатЭдя╕П"
        )
    
        return {"output": ""}
    
    
    # (The old "waiting_clear_confirmation" yes/no flow was removed: it ran before the safety gate and
    #  accepted loose answers such as "sure" from any source. Clearing memory now asks through
    #  safety.SafetyGate - see CLEAR ALL below.)

    
    
    
    # =====================================================
    # NEW MEMORY VALUE
    # =====================================================
    
    if waiting_new_value:
    
        remember(
            memory,
            pending_key,
            user
        )
    
    
        set_context(
            pending_key,
            user
        )
    
    
        print(
            f"Lily: Got it! Your {pending_key} "
            f"is now {user}. тЭдя╕П"
        )
    
    
        pending_key = None
    
        waiting_new_value = False
    
        return {"output": ""}
    
    
    
    # =====================================================
    # MEMORY CONFIRMATION
    # =====================================================
    
    if waiting_memory_confirmation:
    
    
        if is_yes(user):
    
            print(
                f"Lily: Okay! I'll remember "
                f"your {pending_key} is "
                f"{pending_value}. тЭдя╕П"
            )
    
            remember(
                memory,
                pending_key,
                pending_value
            )
    
    
            set_context(
                pending_key,
                pending_value
            )
    
    
            pending_key = None
    
            pending_value = None
    
            waiting_memory_confirmation = False
    
            return {"output": ""}
    
    
    
        elif is_no(user):
    
            print(
                f"Lily: What is your correct "
                f"{pending_key}?"
            )
    
            waiting_new_value = True
    
            waiting_memory_confirmation = False
    
            return {"output": ""}
    
    


    # =====================================================
    # IDENTITY  (deterministic; names come from configuration)
    # =====================================================

    _assistant_name, _user_name = identity.get_names(memory)

    identity_reply = identity.match_identity_question(
        user, _assistant_name, _user_name
    )

    if identity_reply:
        print("Lily:", identity_reply)
        return {"output": identity_reply}

    # =====================================================
    # PRACTICAL DESKTOP COMMANDS (processes, close app, open site, cancel shutdown)
    # =====================================================

    extra_reply = extra_commands.handle(user, origin=_origin)

    if extra_reply is not None:
        print("Lily:", extra_reply)
        return {"output": extra_reply}

    # =========================================================
    # NATURAL LANGUAGE TOOL SELECTION
    # =========================================================
    
    tool_intent = understand_tool(user)
    
    if tool_intent:
    
        tool_name = tool_intent["tool"]
    
        tool_args = tool_intent["args"]
    
    
        # =====================================================
        # SCREENSHOT
        # =====================================================
    
        if tool_name == "take_screenshot":
    
            tool_result = tool_manager.run(
                tool_name,
                *tool_args
            )
    
            if not tool_result["success"]:
    
                print(
                    "Lily: The screenshot tool failed."
                )
    
                print(
                    "Reason:",
                    tool_result["message"]
                )
    
            else:
    
                result = tool_result["result"]
    
                if result.get("success"):
    
                    print(
                        "Lily: Screenshot saved here:"
                    )
    
                    print(
                        result["filename"]
                    )
    
                else:
    
                    print(
                        "Lily: I couldn't take the screenshot."
                    )
    
                    print(
                        "Error:",
                        result.get(
                            "error",
                            "Unknown error."
                        )
                    )
    
            return {"output": ""}
    
    
        # =====================================================
        # RUN THE TOOL
        # =====================================================
    
        tool_result = tool_manager.run(
            tool_name,
            *tool_args
        )

        if not isinstance(tool_result, dict) or not tool_result.get("success"):
            print("Lily: The tool failed.")
            if isinstance(tool_result, dict):
                print("Reason:", tool_result.get("message", "Unknown error."))
            else:
                print("Reason:", tool_result)
            return {"output": ""}

        result = tool_result.get("result")
    
    
        # =====================================================
        # TOOL CONFIRMATION REQUIRED  (central safety gate)
        # =====================================================

        if (
            isinstance(result, dict)
            and result.get("confirmation_required")
        ):
            gate = safety.get_gate()

            if tool_name == "delete_path":
                target = result.get("path")
                reason = safety.protected_reason(target)
                if reason:
                    print(f"Lily: I won't delete that, because it is {reason}.")
                    return {"output": ""}
                print(
                    "Lily:",
                    gate.request(
                        f"Delete {target}?",
                        lambda t=target: system_actions.delete_path(t),
                        detail="It goes to the Recycle Bin when possible."
                    )
                )
                return {"output": ""}

            elif tool_name == "restart_computer":
                print(
                    "Lily:",
                    gate.request(
                        "Restart your computer?",
                        lambda: system_actions.power_action("restart"),
                        detail="You'll get a short moment to cancel."
                    )
                )
                return {"output": ""}

            elif tool_name == "shutdown_computer":
                print(
                    "Lily:",
                    gate.request(
                        "Shut down your computer?",
                        lambda: system_actions.power_action("shutdown"),
                        detail="You'll get a short moment to cancel."
                    )
                )
                return {"output": ""}

        if not tool_result["success"]:
    
            print(
                "Lily: The tool failed."
            )
    
            print(
                "Reason:",
                tool_result.get(
                    "message",
                    "Unknown error."
                )
            )
    
            return {"output": ""}
        
        
        # =====================================================
        # TOOL: CREATE TEXT FILE
        # =====================================================
    
        if tool_name == "create_text_file":
    
            if isinstance(result, dict):
    
                if result.get("success"):
    
                    path = result.get(
                        "path",
                        tool_args[0]
                    )
    
                    filename = os.path.basename(
                        path
                    )
    
                    print(
                        f"Lily: Created {filename} successfully. ЁЯУД"
                    )
    
                else:
    
                    print(
                        "Lily: I couldn't create the file."
                    )
    
                    print(
                        "Error:",
                        result.get(
                            "error",
                            "Unknown error."
                        )
                    )
    
            else:
    
                print(
                    "Lily: The file was created successfully. ЁЯУД"
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: WRITE TEXT FILE
        # =====================================================
    
        if tool_name == "write_text_file":
    
            if isinstance(result, dict):
    
                if result.get("success"):
    
                    path = result.get(
                        "path",
                        tool_args[0]
                    )
    
                    filename = os.path.basename(
                        path
                    )
    
                    print(
                        f"Lily: Done! I wrote the text "
                        f"into {filename}. тЬНя╕П"
                    )
    
                else:
    
                    print(
                        "Lily: I couldn't write to the file."
                    )
    
                    print(
                        "Error:",
                        result.get(
                            "error",
                            "Unknown error."
                        )
                    )
    
            else:
    
                print(
                    "Lily: Done! I wrote the text into the file. тЬНя╕П"
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: READ TEXT FILE
        # =====================================================
    
        if tool_name == "read_text_file":
    
            if isinstance(result, dict):
    
                if result.get("success"):
    
                    path = result.get(
                        "path",
                        tool_args[0]
                    )
    
                    filename = os.path.basename(
                        path
                    )
    
                    content = result.get(
                        "content",
                        ""
                    )
    
                    print(
                        f"Lily: Here's what's inside "
                        f"{filename}: ЁЯУЦ"
                    )
    
                    print()
    
                    if content:
    
                        print(
                            content
                        )
    
                    else:
    
                        print(
                            "(The file is empty.)"
                        )
    
                else:
    
                    print(
                        "Lily: I couldn't read the file."
                    )
    
                    print(
                        "Error:",
                        result.get(
                            "error",
                            "Unknown error."
                        )
                    )
    
            else:
    
                print(
                    "Lily: I couldn't read that file."
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: OPEN PATH
        # =====================================================
    
        if tool_name == "open_path":
    
            if isinstance(result, dict):
    
                if result.get("success"):
    
                    print(
                        f"Lily: Opening "
                        f"{result.get('path', tool_args[0])} ЁЯЪА"
                    )
    
                else:
    
                    print(
                        "Lily: I couldn't open that."
                    )
    
                    print(
                        "Error:",
                        result.get(
                            "error",
                            "Unknown error."
                        )
                    )
    
            else:
    
                print(
                    f"Lily: Opening {tool_args[0]} ЁЯЪА"
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: GET FOLDER SIZE
        # =====================================================
    
        if tool_name == "get_folder_size":
    
            if isinstance(result, dict):
    
                if result.get("success"):
    
                    print(
                        f"Lily: Your folder is using "
                        f"{result.get('mb', 0):.2f} MB "
                        f"of storage. ЁЯТ╛"
                    )
    
                else:
    
                    print(
                        "Lily: I couldn't calculate the folder size."
                    )
    
                    print(
                        "Error:",
                        result.get(
                            "error",
                            "Unknown error."
                        )
                    )
    
            else:
    
                print(
                    "Lily: I couldn't calculate the folder size."
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: BACKUP
        # =====================================================
    
        if tool_name == "backup":
    
            if isinstance(result, (tuple, list)) and len(result) >= 2:
    
                backup_folder = result[0]
    
                copied = result[1]
    
                print(
                    "Lily: Backup created successfully. ЁЯТ╛"
                )
    
                print(
                    f"Location: {backup_folder}"
                )
    
                if copied:
    
                    print(
                        "Files backed up:"
                    )
    
                    for filename in copied:
    
                        print(
                            f"- {filename}"
                        )
    
                else:
    
                    print(
                        "No files were available to back up."
                    )
    
            elif isinstance(result, dict):
    
                if result.get("success"):
    
                    print(
                        "Lily: Backup created successfully. ЁЯТ╛"
                    )
    
                    if result.get("path"):
    
                        print(
                            f"Location: {result['path']}"
                        )
    
                else:
    
                    print(
                        "Lily: I couldn't create the backup."
                    )
    
                    print(
                        "Error:",
                        result.get(
                            "error",
                            "Unknown error."
                        )
                    )
    
            else:
    
                print(
                    "Lily: Backup created successfully. ЁЯТ╛"
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: LIST BACKUPS
        # =====================================================
    
        if tool_name == "list_backups":
    
            if isinstance(result, list):
    
                if not result:
    
                    print(
                        "Lily: You don't have any backups yet. ЁЯУж"
                    )
    
                else:
    
                    print(
                        "Lily: Your backups are:"
                    )
    
                    for backup in result:
    
                        print(
                            f"- {backup}"
                        )
    
            elif isinstance(result, dict):
    
                if result.get("success"):
    
                    backups = result.get(
                        "backups",
                        []
                    )
    
                    if not backups:
    
                        print(
                            "Lily: You don't have any backups yet. ЁЯУж"
                        )
    
                    else:
    
                        print(
                            "Lily: Your backups are:"
                        )
    
                        for backup in backups:
    
                            print(
                                f"- {backup}"
                            )
    
                else:
    
                    print(
                        "Lily: I couldn't get your backups."
                    )
    
                    print(
                        "Error:",
                        result.get(
                            "error",
                            "Unknown error."
                        )
                    )
    
            else:
    
                print(
                    "Lily: I couldn't get your backups."
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: SYSTEM INFO
        # =====================================================
    
        if tool_name == "system_info":
    
            if isinstance(result, dict):
    
                print(
                    "Lily: Here's your system information:"
                )
    
                for key, value in result.items():
    
                    print(
                        f"     {key}: {value}"
                    )
    
            else:
    
                print(
                    "Lily: Here's your system information:"
                )
    
                print(
                    result
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: CPU
        # =====================================================
    
        if tool_name == "cpu_info":
    
            if isinstance(result, dict):
    
                print(
                    "Lily: Here's your CPU information:"
                )
    
                print(
                    f"     CPU usage: "
                    f"{result.get('cpu_percent', 0)}%"
                )
    
                print(
                    f"     CPU cores: "
                    f"{result.get('cpu_count', 'Unknown')}"
                )
    
            else:
    
                print(
                    "Lily: Here's your CPU information:"
                )
    
                print(
                    result
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: MEMORY
        # =====================================================
    
        if tool_name == "memory_info":
    
            if isinstance(result, dict):
    
                print(
                    f"Lily: You're using "
                    f"{result.get('used_gb', 0)} GB "
                    f"of RAM out of "
                    f"{result.get('total_gb', 0)} GB."
                )
    
                print(
                    f"Lily: That's about "
                    f"{result.get('percent', 0)}% "
                    f"of your RAM."
                )
    
                print(
                    f"Lily: You have "
                    f"{result.get('available_gb', 0)} GB "
                    f"available."
                )
    
            else:
    
                print(
                    "Lily: Here's your memory information:"
                )
    
                print(
                    result
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: DISK
        # =====================================================
    
        if tool_name == "disk_info":
    
            if isinstance(result, dict):
    
                print(
                    f"Lily: Your drive has "
                    f"{result.get('total_gb', 0)} GB "
                    f"of total space."
                )
    
                print(
                    f"Lily: You're using "
                    f"{result.get('used_gb', 0)} GB."
                )
    
                print(
                    f"Lily: You have "
                    f"{result.get('free_gb', 0)} GB free."
                )
    
                print(
                    f"Lily: That's "
                    f"{result.get('percent', 0)}% "
                    f"currently used."
                )
    
            else:
    
                print(
                    "Lily: Here's your disk information:"
                )
    
                print(
                    result
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: BATTERY
        # =====================================================
    
        if tool_name == "battery_info":
    
            if isinstance(result, dict):
    
                print(
                    "Lily: Here's your battery information:"
                )
    
                print(
                    f"     Battery: "
                    f"{result.get('percent', 0)}%"
                )
    
                print(
                    f"     Charging: "
                    f"{'Yes' if result.get('charging') else 'No'}"
                )
    
            else:
    
                print(
                    "Lily: Here's your battery information:"
                )
    
                print(
                    result
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: NETWORK
        # =====================================================
    
        if tool_name == "network_info":
    
            print(
                "Lily: Here's your network information:"
            )
    
            if isinstance(result, list):
    
                for adapter in result:
    
                    print(
                        adapter
                    )
    
            elif isinstance(result, dict):
    
                for key, value in result.items():
    
                    print(
                        f"     {key}: {value}"
                    )
    
            else:
    
                print(
                    result
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: USER INFO
        # =====================================================
    
        if tool_name == "user_info":
    
            if isinstance(result, dict):
    
                print(
                    "Lily: Your Windows username is "
                    f"{result.get('username', 'Unknown')}."
                )
    
                print(
                    "Lily: Your computer name is "
                    f"{result.get('computer_name', 'Unknown')}."
                )
    
            else:
    
                print(
                    "Lily: Here's your user information:"
                )
    
                print(
                    result
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: DATE / TIME
        # =====================================================
    
        if tool_name == "datetime_info":
    
            if isinstance(result, dict):
    
                print(
                    "Lily: Here's the current date and time:"
                )
    
                for key, value in result.items():
    
                    print(
                        f"     {key}: {value}"
                    )
    
            else:
    
                print(
                    "Lily: Here's the current date and time:"
                )
    
                print(
                    result
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: LAUNCH PROGRAM
        # =====================================================
    
        if tool_name == "launch_program":
    
            if isinstance(result, dict):
    
                if result.get("success"):
    
                    print(
                        f"Lily: Opening {tool_args[0]} ЁЯЪА"
                    )
    
                else:
    
                    print(
                        "Lily: I couldn't open that."
                    )
    
                    print(
                        "Error:",
                        result.get(
                            "error",
                            "Unknown error."
                        )
                    )
    
            else:
    
                print(
                    f"Lily: Opening {tool_args[0]} ЁЯЪА"
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: LIST FILES
        # =====================================================
    
        if tool_name == "list_files":
    
            if not isinstance(result, dict):
    
                print(
                    "Lily: I couldn't list those files."
                )
    
                return {"output": ""}
    
    
            if not result.get("success"):
    
                print(
                    "Lily: I couldn't list that folder."
                )
    
                print(
                    "Reason:",
                    result.get(
                        "message",
                        result.get(
                            "error",
                            "Unknown error."
                        )
                    )
                )
    
                return {"output": ""}
    
    
            folder = result.get(
                "folder",
                "that folder"
            )
    
            items = result.get(
                "items",
                []
            )
    
            print(
                f"Lily: Here's what's in {folder}: ЁЯУБ"
            )
    
    
            if not items:
    
                print(
                    "     The folder is empty."
                )
    
            else:
    
                for item in items:
    
                    item_type = item.get(
                        "type",
                        "item"
                    )
    
                    item_name = item.get(
                        "name",
                        "Unknown"
                    )
    
                    print(
                        f"     {item_type}: {item_name}"
                    )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: SEARCH FILES
        # =====================================================
    
        if tool_name == "search_files":
    
            if not isinstance(result, dict):
    
                print(
                    "Lily: I couldn't search for that file."
                )
    
                return {"output": ""}
    
    
            if not result.get("success"):
    
                print(
                    "Lily: I couldn't search that folder."
                )
    
                print(
                    "Reason:",
                    result.get(
                        "message",
                        result.get(
                            "error",
                            "Unknown error."
                        )
                    )
                )
    
                return {"output": ""}
    
    
            results = result.get(
                "results",
                []
            )
    
    
            if not results:
    
                print(
                    "Lily: I couldn't find that file. ЁЯФО"
                )
    
            else:
    
                print(
                    "Lily: I found it here: ЁЯФО"
                )
    
                for path in results:
    
                    print(
                        f"     {path}"
                    )
    
            return {"output": ""}
    
    
        # =====================================================
        # TOOL: LOCK COMPUTER
        # =====================================================
    
        if tool_name == "lock_computer":
    
            if isinstance(result, dict):
    
                if result.get("success"):
    
                    print(
                        "Lily: Locking your computer. ЁЯФТ"
                    )
    
                else:
    
                    print(
                        "Lily: I couldn't lock the computer."
                    )
    
                    print(
                        "Error:",
                        result.get(
                            "error",
                            "Unknown error."
                        )
                    )
    
            else:
    
                print(
                    "Lily: Locking your computer. ЁЯФТ"
                )
    
            return {"output": ""}
    
    
        # =====================================================
        # UNKNOWN TOOL
        # =====================================================
    
        print(
            f"Lily: I successfully used the "
            f"'{tool_name}' tool, but I don't have "
            f"a display handler for it yet."
        )
    
        print(
            "Result:",
            result
        )
    
        return {"output": ""}
    
    
    # =========================================================
    # NORMAL INTENT ENGINE
    # =========================================================
    # =========================================================
    # NORMAL INTENT ENGINE
    # =========================================================
    
    intent = understand(user)
    
    intent_type = intent["intent"]
    key = intent["key"]
    value = intent["value"]
    
    
    
    
    # =====================================================
    # SAVE PREFERENCE
    # =====================================================
    
    if intent_type == "SAVE_PREFERENCE":
    
        remember(
            memory,
            key,
            value
        )
    
    
        print(
            f"Lily: Got it! I'll remember your {key} as {value}. тЭдя╕П"
        )
    
    
        return {"output": ""}
    
    
    # =====================================================
    # GOALS
    # =====================================================
    
    if intent_type == "ADD_GOAL":
    
        add_goal(
            goals,
            value
        )
    
        save_goals(
            goals
        )
    
    
        print(
            f"Lily: I'll remember your goal: {value}. ЁЯОптЭдя╕П"
        )
    
        return {"output": ""}
    
    
    
    if intent_type == "LIST_GOALS":
    
        if not goals:
    
            print(
                "Lily: You don't have any goals yet. ЁЯОп"
            )
    
        else:
    
            print(
                "Lily: Your goals:"
            )
    
            for goal in goals:
    
                status = (
                    "completed"
                    if goal["completed"]
                    else "active"
                )
    
                print(
                    f"- {goal['task']} ({status})"
                )
    
        return {"output": ""}
    
    
    
    if intent_type == "COMPLETE_GOAL":
    
        success = complete_goal(
            goals,
        value
        )
    
        save_goals(
            goals
        )
    
    
        if success:
    
            print(
                f"Lily: Congratulations! I marked {value} as completed. ЁЯОЙ"
            )
    
        else:
    
            print(
            f"Lily: I couldn't find that goal."
            )
    
        return {"output": ""}
    
    
    # =====================================================
    # LIST MEMORIES
    # =====================================================
    
    if intent_type == "LIST_MEMORIES":
    
        if not memory:
    
            print(
                "Lily: I don't remember anything yet. ЁЯза"
            )
    
    
        else:
    
            print(
                "Lily: I remember:"
            )
    
    
            for k, v in memory.items():
    
                category = v.get(
                    "category",
                    "general"
                )
    
    
                importance = v.get(
                    "importance",
                    "normal"
                )
    
    
                print(
                    f"- [{category}] {k}: {v['value']} "
                    f"(importance: {importance})"
                )
    
    
        return {"output": ""}
    
    
    # =====================================================
    # SHOW CATEGORY
    # =====================================================
    
    if intent_type == "SHOW_CATEGORY":
    
        if key == "preferences":
    
            category_memory = get_memories_by_category(
                memory,
                "preferences"
            )
    
            behavior_memory = get_memories_by_category(
                memory,
                "behavior"
            )
    
            category_memory.update(
                behavior_memory
            )
    
        else:
    
            category_memory = get_memories_by_category(
                memory,
                key
            )
    
    
        if not category_memory:
    
            print(
                f"Lily: I don't have any {key} memories yet."
            )
    
    
        else:
    
            print(
                f"Lily: Your {key} memories:"
            )
    
    
            for k, v in category_memory.items():
    
                print(
                    f"- {k}: {v['value']}"
                )
    
    
        return {"output": ""}
    
    
    # =====================================================
    # COUNT MEMORIES
    # =====================================================
    
    if intent_type == "COUNT_MEMORIES":
    
        print(
            f"Lily: I have {len(memory)} memories about you. ЁЯза"
        )
    
        return {"output": ""}
    
    
    
    # =====================================================
    # CLEAR ALL
    # =====================================================
    
    if intent_type == "CLEAR_ALL_MEMORIES":
        if memory:
            print(
                "Lily:",
                safety.get_gate().request(
                    "Forget all %d memories?" % len(memory),
                    _clear_all_memories,
                    detail="A safety copy of memory.json is kept next to it."
                )
            )
        else:
            print(
                "Lily: I don't have any memories to delete."
            )
        return {"output": ""}
    
    
    # =====================================================
    # SAVE LIKE
    # =====================================================
    
    if intent_type == "SAVE_LIKE":
    
        remember(
            memory,
            key,
            value
        )
    
    
        set_context(
            key,
            value
        )
    
    
        print(
            f"Lily: Got it! I'll remember that you like {value}. тЭдя╕П"
        )
    
    
        return {"output": ""}
    
    
    # =====================================================
    # SAVE MEMORY
    # =====================================================
    
    if intent_type == "SAVE_MEMORY":
    
        remember(
            memory,
            key,
            value
        )
    
        set_state(
            state,
            "last_action",
            f"saved memory: {key}"
        )
    
    
        set_context(
            key,
            value
        )
    
    
        print(
            f"Lily: Got it! I'll remember "
            f"your {key} is {value}. тЭдя╕П"
        )
    
        return {"output": ""}
    
    
    
    # =====================================================
    # UPDATE MEMORY
    # =====================================================
    
    if intent_type == "UPDATE_MEMORY":
    
        old_memory = find_memory(
            memory,
            key
        )
    
        old = None
    
        if old_memory:
            old = old_memory["value"]
    
    
        remember(
            memory,
            key,
            value
        )
    
    
        set_state(
            state,
            "last_action",
            f"updated memory: {key}"
        )
        
        set_context(
            key,
            value
        )
    
    
        if old:
    
            print(
                f"Lily: Updated your {key} "
                f"from {old} to {value}. тЭдя╕П"
            )
    
        else:
    
            print(
                f"Lily: I saved your {key} as {value}. тЭдя╕П"
            )
    
    
        return {"output": ""}
    
    
    
    # =====================================================
    # READ MEMORY
    # =====================================================
    
    if intent_type == "READ_MEMORY":
    
        result = find_memory(
            memory,
            key
        )
    
    
        if result:
            
            set_context(
                key,
                result["value"]
            )
    
            pending_key = key
    
            pending_value = result["value"]
    
            waiting_memory_confirmation = True
    
    
            print(
                f"Lily: Your {key} is "
                f"{result['value']}, right?"
            )
    
    
        else:
    
            print(
                f"Lily: I don't have your {key} saved yet."
            )
    
    
        return {"output": ""}
    
    
    # =====================================================
    # CONTEXTUAL DISLIKE
    # =====================================================
    
    if intent_type == "CONTEXTUAL_DISLIKE":
    
        if has_context():
    
            context = get_context()
    
            context_key = context["key"]
    
            context_value = context["value"]
    
    
            if context_key.startswith("favorite "):
    
                category = context_key[
                    len("favorite "):
                ]
    
                dislike_key = (
                    "dislike " + category
                )
    
                remember(
                    memory,
                    dislike_key,
                    context_value
                )
    
    
                if context_key in memory:
    
                    del memory[context_key]
    
                    save_memory(
                        memory
                    )
    
    
                print(
                    f"Lily: Got it. I've noted "
                    f"that you don't like "
                    f"{context_value} anymore. тЭдя╕П"
                )
    
    
                clear_context()
    
            else:
    
                dislike_key = (
                    "dislike " + context_key
                )
    
                remember(
                    memory,
                    dislike_key,
                    context_value
                )
    
                clear_context()
    
                print(
                    f"Lily: Got it. I've noted "
                    f"that you don't like "
                    f"{context_value} anymore. тЭдя╕П"
                )
    
        else:
    
            print(
                "Lily: I understand you don't "
                "like something anymore, but "
                "I'm not sure what you mean."
            )
            
            
        return {"output": ""}
    
    # =====================================================
    # CONTEXTUAL USED TO LIKE
    # =====================================================
    
    if intent_type == "CONTEXTUAL_USED_TO_LIKE":
    
        if has_context():
    
            context = get_context()
    
            context_key = context["key"]
    
            context_value = context["value"]
    
    
            if context_key.startswith("favorite "):
    
                category = context_key[
                    len("favorite "):
                ]
    
                old_key = (
                    "used to like "
                    + category
                )
    
                remember(
                    memory,
                    old_key,
                    context_value
                )
                
                clear_context()
    
    
                print(
                    f"Lily: Got it. I'll remember "
                    f"that you used to like "
                    f"{context_value}. тЭдя╕П"
                )
    
    
            else:
    
                old_key = (
                    "used to like "
                    + context_key
                )
    
                remember(
                    memory,
                    old_key,
                    context_value
                )
    
                clear_context()
    
                print(
                    f"Lily: Got it. I'll remember "
                    f"that you used to like "
                    f"{context_value}. тЭдя╕П"
                )         
    
    
        else:
    
            print(
                "Lily: I understand you used "
                "to like something, but I don't "
                "know what you're referring to."
            )
    
    
        return {"output": ""}
    
    
    # =====================================================
    # DELETE MEMORY
    # =====================================================
    
    if intent_type == "DELETE_MEMORY":
    
        if forget_memory(
            memory,
            key
            ):
            
            set_state(
                state,
                "last_action",
                f"deleted memory: {key}"
            )
    
            print(
                f"Lily: I forgot your {key}. тЭдя╕П"
            )
    
        else:
    
            print(
                f"Lily: I don't have {key} saved."
            )
    
    
        return {"output": ""}
    
    
    # =========================================================
    # BACKUP
    # =========================================================
    
    if lower == "backup":
    
        result = tool_manager.run(
            "backup"
        )
    
        if result["success"]:
    
            backup_folder, copied = result["result"]
    
            print(
                "Lily: Backup created successfully! ЁЯУжтЭдя╕П"
            )
    
            print(
                "Location:",
                backup_folder
            )
    
            if copied:
    
                print(
                    "Files:",
                    ", ".join(copied)
                )
    
            else:
    
                print(
                    "Lily: There were no files to back up."
                )
    
        else:
    
            print(
                "Lily: I couldn't create the backup."
            )
    
            print(
                "Error:",
                result["message"]
            )
    
        return {"output": ""}
    
    
    # =========================================================
    # SHOW BACKUPS
    # =========================================================
    
    if lower == "show backups":
    
        result = tool_manager.run(
            "list_backups"
        )
    
        if not result["success"]:
    
            print(
                "Lily: I couldn't get the backup list."
            )
    
            print(
                "Error:",
                result["message"]
            )
    
        else:
    
            backups = result["result"]
    
            if not backups:
    
                print(
                    "Lily: You don't have any backups yet. ЁЯУж"
                )
    
            else:
    
                print(
                    "Lily: Your backups:"
                )
    
                for backup in backups:
    
                    print(
                        "-",
                        backup
                    )
    
        return {"output": ""}
    
    
    # =========================================================
    # SYSTEM INFO
    # =========================================================
    
    if lower == "system info":
    
        result = tool_manager.run(
            "system_info"
        )
    
        if result["success"]:
    
            info = result["result"]
    
            print(
                "Lily: Here's what I know about the computer:"
            )
    
            print(
                "System:",
                info["system"]
            )
    
            print(
                "Release:",
                info["release"]
            )
    
            print(
                "Machine:",
                info["machine"]
            )
    
            print(
                "Processor:",
                info["processor"]
            )
    
        else:
    
            print(
                "Lily: I couldn't get the system information."
            )
    
            print(
                "Error:",
                result["message"]
            )
    
        return {"output": ""}
    
    
    # =========================================================
    # CPU INFO
    # =========================================================
    
    if lower == "cpu info":

        result = tool_manager.run("cpu_info")

        if not result.get("success"):
            print("Lily: I couldn't get the CPU information.")
            print("Error:", result.get("message", "Unknown error."))
            return {"output": ""}

        result = result.get("result", {})
        print(
            "Lily: Here's your CPU information:"
        )
    
        if isinstance(result, dict):
    
            print(
                f"     CPU usage: {result.get('cpu_percent', 0)}%"
            )
    
            print(
                f"     CPU cores: {result.get('cpu_count', 0)}"
            )
    
        else:
    
            print(
                "     ",
                result
            )
    
        return {"output": ""}
    
    
    # =========================================================
    # MEMORY INFO
    # =========================================================
    
    if lower == "memory info":
    
        result = tool_manager.run(
            "memory_info"
        )
    
        if result["success"]:
    
            info = result["result"]
    
            print(
                "Lily: RAM usage:",
                info["percent"],
                "%"
            )
    
            print(
                "Used:",
                info["used_gb"],
                "GB"
            )
    
            print(
                "Available:",
                info["available_gb"],
                "GB"
            )
    
        else:
    
            print(
                "Lily: I couldn't get the memory information."
            )
    
            print(
                "Error:",
                result["message"]
            )
    
        return {"output": ""}
    
    
    # =========================================================
    # DISK INFO
    # =========================================================
    
    if lower == "disk info":
    
        result = tool_manager.run(
            "disk_info"
        )
    
        if result["success"]:
    
            info = result["result"]
    
            print(
                "Lily: Disk usage:",
                info["percent"],
                "%"
            )
    
            print(
                "Used:",
                info["used_gb"],
                "GB"
            )
    
            print(
                "Free:",
                info["free_gb"],
                "GB"
            )
    
        else:
    
            print(
                "Lily: I couldn't get the disk information."
            )
    
            print(
                "Error:",
                result["message"]
            )
    
        return {"output": ""}
    
    
    # =========================================================
    # SPEAK TEST
    # =========================================================
    
    if lower == "speak test":
        _test_user = identity.get_names(memory)[1]
        message = (
            "Hello" + (", " + _test_user if _test_user else "") + ". "
            "My voice system is working."
        )
    
        print(
            "Lily:",
            message
        )
    
        speak(
            message
        )
    
        return {"output": ""}
        
        
    # =========================================================
    # SHOW PLUGINS
    # =========================================================
    
    if lower == "show plugins":
    
        plugins = plugin_manager.list_plugins()
    
        if not plugins:
    
            print(
                "Lily: No plugins are loaded."
            )
    
        else:
    
            print(
                "Lily: Loaded plugins:"
            )
    
            for plugin in plugins:
    
                print(
                    "-",
                    plugin["name"],
                    ":",
                    plugin["description"]
                )
    
        return {"output": ""}
    
    
    # =========================================================
    # TEST PLUGIN
    # =========================================================
    
    if lower == "test plugin":
    
        result = plugin_manager.run(
            "hello_plugin"
        )
    
        if result["success"]:
    
            print(
                "Lily:",
                result["result"]
            )
    
        else:
    
            print(
                "Lily:",
                result["message"]
            )
    
        return {"output": ""}
    
    
    # =========================================================
    # BATTERY INFO
    # =========================================================
    
    if lower == "battery info":

        result = tool_manager.run("battery_info")

        if not result.get("success"):
            print("Lily: I couldn't get the battery information.")
            print("Error:", result.get("message", "Unknown error."))
            return {"output": ""}

        result = result.get("result", {})
        print(
            "Lily: Here's your battery information:"
        )
    
        if isinstance(result, dict):
    
            available = result.get(
                "available",
                False
            )
    
            percent = result.get(
                "percent",
                0
            )
    
            plugged = result.get(
                "plugged",
                False
            )
    
            if not available:
    
                print(
                    "     Battery information is not available."
                )
    
            else:
    
                print(
                    f"     Battery: {percent}%"
                )
    
                print(
                    "     Charging:",
                    "Yes" if plugged else "No"
                )
    
        else:
    
            print(
                "     ",
                result
            )
    
        return {"output": ""}
    
    
    # =========================================================
    # NETWORK INFO
    # =========================================================
    
    if lower == "network info":

        result = tool_manager.run("network_info")

        if not result.get("success"):
            print("Lily: I couldn't get the network information.")
            print("Error:", result.get("message", "Unknown error."))
            return {"output": ""}

        result = result.get("result", [])
        print(
            "Lily: Here's your network information:"
        )
    
        if isinstance(result, list):
    
            for network in result:
    
                name = network.get(
                    "name",
                    "Unknown network"
                )
    
                ipv4 = network.get(
                    "ipv4",
                    []
                )
    
                print()
                print(
                    f"     {name}"
                )
    
                if ipv4:
    
                    for address in ipv4:
    
                        print(
                            f"     IP address: {address}"
                        )
    
                else:
    
                    print(
                        "     IP address: None"
                    )
    
        else:
    
            print(
                "     ",
                result
            )
    
        return {"output": ""}
    
    
    # =========================================================
    # USER INFO
    # =========================================================
    
    if lower == "user info":
    
        result = tool_manager.run(
            "user_info"
        )
    
        if result["success"]:
    
            info = result["result"]
    
            print(
                "Lily: Current user:",
                info["username"]
            )
    
            print(
                "Computer name:",
                info["computer_name"]
            )
    
        else:
    
            print(
                "Lily: I couldn't get user information."
            )
    
            print(
                "Error:",
                result["message"]
            )
    
        return {"output": ""}
    
    
    # =========================================================
    # DATE AND TIME
    # =========================================================
    
    if lower in ("date and time", "datetime", "date time", "current time", "what time is it"):

        result = tool_manager.run("datetime_info")

        if not result.get("success"):
            print("Lily: I couldn't get the current date and time.")
            print("Error:", result.get("message", "Unknown error."))
            return {"output": ""}

        result = result.get("result", {})

        if isinstance(result, dict):
    
            day = result.get(
                "day",
                "Unknown day"
            )
    
            date = result.get(
                "date",
                "Unknown date"
            )
    
            time = result.get(
                "time",
                "Unknown time"
            )
    
            print(
                f"Lily: It's {day}, {date}."
            )
    
            print(
                f"Lily: The current time is {time}."
            )
    
        else:
    
            print(
                "Lily:",
                result
            )
    
        return {"output": ""}
    
    
    # =========================================================
    # OPEN PROGRAM
    # =========================================================
    
    if lower.startswith("open "):
    
        program = user[5:].strip()
    
        if not program:
    
            print(
                "Lily: What should I open?"
            )
    
            return {"output": ""}
    
        result = tool_manager.run(
            "launch_program",
            program
        )
    
        if result["success"]:
    
            print(
                "Lily: Opening",
                program,
                "ЁЯЪА"
            )
    
        else:
    
            info = result["result"]
    
            if not info["success"]:
    
                print(
                    "Lily: I couldn't open that."
                )
    
                print(
                    "Error:",
                    info["error"]
                )
    
        return {"output": ""}
    
    # =========================================================
    # LIST FILES
    # =========================================================
    
    if lower.startswith("list files"):
    
        folder = user[len("list files"):].strip()
    
        if not folder:
    
            folder = os.getcwd()
    
        tool_result = tool_manager.run(
            "list_files",
            folder
        )
    
        if not tool_result["success"]:
    
            print(
                "Lily: The file tool failed."
            )
    
            print(
                "Reason:",
                tool_result["message"]
            )
    
        else:
    
            result = tool_result["result"]
    
            if not result["success"]:
    
                print(
                    "Lily: I couldn't list that folder."
                )
    
                print(
                    "Reason:",
                    result["message"]
                )
    
            else:
    
                print(
                    "Lily: Contents of:",
                    result["folder"]
                )
    
                items = result["items"]
    
                if not items:
    
                    print(
                        "Lily: The folder is empty."
                    )
    
                else:
    
                    for item in items:
    
                        print(
                            "-",
                            item["type"],
                            ":",
                            item["name"]
                        )
    
        return {"output": ""}
    
    
    # =========================================================
    # SEARCH FILES
    # =========================================================
    
    if lower.startswith("search files"):
    
        search_text = user[len("search files"):].strip()
    
        parts = search_text.rsplit(" ", 1)
    
        if len(parts) != 2:
    
            print(
                "Lily: Use: search files <folder> <filename>"
            )
    
            return {"output": ""}
    
        folder = parts[0]
        filename = parts[1]
    
        tool_result = tool_manager.run(
            "search_files",
            folder,
            filename
        )
    
        if not tool_result["success"]:
    
            print(
                "Lily: The file tool failed."
            )
    
            print(
                "Reason:",
                tool_result["message"]
            )
    
        else:
    
            result = tool_result["result"]
    
            if not result["success"]:
    
                print(
                    "Lily: I couldn't search that folder."
                )
    
                print(
                    "Reason:",
                    result["message"]
                )
    
            else:
    
                results = result["results"]
    
                if not results:
    
                    print(
                        "Lily: I couldn't find that file."
                    )
    
                else:
    
                    print(
                        "Lily: I found:"
                    )
    
                    for path in results:
    
                        print(
                            "-",
                            path
                        )
    
        return {"output": ""}
    
    
    # =========================================================
    # SCREENSHOT
    # =========================================================
    
    if lower == "take screenshot":
    
        screenshot_folder = os.path.join(
            os.path.dirname(
                os.path.abspath(__file__)
            ),
            "screenshots"
        )
    
        os.makedirs(
            screenshot_folder,
            exist_ok=True
        )
    
        filename = os.path.join(
            screenshot_folder,
            "screenshot_" +
            datetime.now().strftime(
                "%Y-%m-%d_%H-%M-%S"
            ) +
            ".png"
        )
    
        result = tool_manager.run(
            "take_screenshot",
            filename
        )
    
        if result["success"]:
    
            info = result["result"]
    
            if info["success"]:
    
                print(
                    "Lily: Screenshot saved! ЁЯУ╕"
                )
    
                print(
                    "Location:",
                    info["filename"]
                )
    
            else:
    
                print(
                    "Lily: I couldn't take the screenshot."
                )
    
                print(
                    "Error:",
                    info["error"]
                )
    
        else:
    
            print(
                "Lily: The screenshot tool failed."
            )
    
            print(
                "Error:",
                result["message"]
            )
    
        return {"output": ""}
    
                  
    # =========================================================
    # NORMAL AI CHAT
    # =========================================================
    
    brain_result = think(
        user,
        learning
    )
    
    response_mode = brain_result.get(
        "response_mode",
        "normal"
    )
    
    difficulty = brain_result.get(
        "difficulty",
        "normal"
    )
    
    answer_length = brain_result.get(
        "answer_length",
        "normal"
    )
    
    technical_terms = brain_result.get(
        "technical_terms",
        "normal"
    )
    
    
    # =========================================================
    # BUILD RESPONSE INSTRUCTIONS
    # =========================================================
    
    response_instructions = ""
    
    
    # ---------------------------------------------------------
    # RESPONSE MODE
    # ---------------------------------------------------------
    
    if response_mode == "simple":
    
        response_instructions += """
    RESPONSE MODE: SIMPLE
    
    Answer the user in simple everyday English.
    
    Rules:
    - Explain the main idea first.
    - Use short and clear sentences.
    - Explain one idea at a time.
    - Do not assume the user already knows the subject.
    """
    
    
    elif response_mode == "detailed":
    
        response_instructions += """
    RESPONSE MODE: DETAILED
    
    Give the user a detailed explanation.
    
    Rules:
    - Explain the main idea clearly.
    - Break complicated ideas into sections.
    - Explain important concepts.
    - Give examples when useful.
    """
    
    
    # ---------------------------------------------------------
    # DIFFICULTY
    # ---------------------------------------------------------
    
    if difficulty == "beginner":
    
        response_instructions += """
    DIFFICULTY: BEGINNER
    
    The user is a beginner.
    
    Rules:
    - Start from the basics.
    - Do not assume prior knowledge.
    - Use familiar real-world examples.
    - If a technical word is necessary, explain it immediately.
    """
    
    
    # ---------------------------------------------------------
    # ANSWER LENGTH
    # ---------------------------------------------------------
    
    if answer_length == "short":
    
        response_instructions += """
    ANSWER LENGTH: SHORT
    
    Keep the answer concise.
    
    Rules:
    - Focus only on the most important information.
    - Avoid unnecessary background information.
    - Prefer a few clear paragraphs instead of a long lecture.
    """
    
    
    elif answer_length == "long":
    
        response_instructions += """
    ANSWER LENGTH: LONG
    
    Give enough explanation to fully understand the subject.
    
    Rules:
    - Cover the important parts.
    - Use examples when useful.
    - Organize the answer clearly.
    """
    
    
    # ---------------------------------------------------------
    # TECHNICAL TERMS
    # ---------------------------------------------------------
    
    if technical_terms == "low":
    
        response_instructions += """
    TECHNICAL TERMS: LOW
    
    Avoid unnecessary technical terminology.
    
    If an important technical word must be used:
    1. Say the word.
    2. Immediately explain what it means in simple language.
    3. Continue using simple language afterward.
    """
    
    
    elif technical_terms == "normal":
    
        response_instructions += """
    TECHNICAL TERMS: NORMAL
    
    Use technical terms when they are useful.
    
    Explain important technical terms clearly.
    """
    
    
    # =========================================================
    # FINAL RESPONSE RULES
    # =========================================================
    
    response_instructions += """
    
    IMPORTANT:
    
    - Answer the user's actual question.
    - Do not talk about these instructions.
    - Do not mention response modes or response plans.
    - Do not repeat the user's question unnecessarily.
    - Do not invent facts.
    - If you are unsure about something, say so.
    """
    
    
    # =========================================================
    # BUILD AI PROMPT  (identity first, whole-turn history, token budget)
    # =========================================================

    settings = get_settings()
    assistant_name, user_name = identity.get_names(memory)
    profile = prompt_manager.get_profile(settings["chat_template"])

    sections = prompt_manager.build_system_sections(
        assistant_name,
        user_name,
        get_personality_prompt(),
        response_instructions,
        build_learning_prompt(),
        prompt_manager.summarize_memory(memory)
    )

    prompt, prompt_info = prompt_manager.build_chat_prompt(
        sections,
        conversation.turns(),
        user,
        settings["context"],
        settings["chat_max_tokens"] + 64,
        profile
    )

    _log.debug("chat prompt: ~%s tokens (budget %s), %s of %s history turns, dropped sections: %s",
               prompt_info["estimated_tokens"], prompt_info["budget"], prompt_info["turns_included"],
               prompt_info["turns_available"], prompt_info["sections_dropped"] or "none")

    # =========================================================
    # RUN AI ENGINE
    # =========================================================

    try:
        # The saved AI mode (LOCAL / API / AUTO, see core/ai_router.py) decides who answers.
        # LOCAL is the original behaviour: local_generate(prompt, ...) with the same arguments.
        answer = ai_router.chat(
            prompt,
            ai_router.join_system_sections(sections),
            conversation.turns(),
            user,
            max_tokens=settings["chat_max_tokens"],
            timeout=settings["timeout"],
            local_fn=local_generate
        )

    except ai_router.AIError as e:
        # API mode only: show a clear, key-free error and do NOT silently switch models.
        _log.error("Gemini API request failed (%s): %s", e.kind, e)
        print("Lily: " + ai_router.api_failure_message(e))
        return {"output": ""}

    except EngineNotConfigured as e:
        _log.error("local engine not configured: %s", e)
        print("[engine]", e, file=sys.stderr)
        print(
            "Lily: My local AI model isn't set up yet, so I can't chat right now, "
            "but my tools still work."
        )
        return {"output": ""}

    except EngineTimeout:
        _log.error("local engine timed out after %s seconds", settings["timeout"])
        print(
            "Lily: I took too long to think about that, so I stopped. "
            "Please try a shorter question."
        )
        return {"output": ""}

    except EngineInterrupted:
        _log.info("generation interrupted by the user")
        print("Lily: Okay, I stopped.")
        return {"output": ""}

    except EngineCrash as e:
        _log.error("local engine crashed: %s", e)
        print("[engine]", e, file=sys.stderr)
        print("Lily: My AI engine stopped unexpectedly. Please try again.")
        return {"output": ""}

    except Exception as e:
        _log.exception("unexpected error while generating a reply")
        print("[engine]", type(e).__name__, e, file=sys.stderr)
        print("Lily: Something went wrong while I was thinking. Please try again.")
        return {"output": ""}

    fallback_reason = ai_router.last_fallback_reason()
    if fallback_reason:
        # AUTO mode tried Gemini, it failed, and the local model answered instead.
        _log.info("AUTO mode used the local model after a Gemini failure: %s", fallback_reason)
        print("SYS: Gemini was unavailable (%s) - the local model answered instead." % fallback_reason.rstrip("."))

    # =========================================================
    # CLEAN AI RESPONSE
    # =========================================================

    answer = (answer or "").strip()

    answer = answer.encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")

    answer = prompt_manager.strip_template_tokens(answer).strip()

    # the "cut off by the token limit" heuristic only applies to the small local model
    looks_truncated = ai_router.last_backend() != "gemini" and len(answer) / 4.5 >= settings["chat_max_tokens"] * 0.9
    answer = trim_incomplete_sentence(answer, looks_truncated)

    answer, identity_fixed = identity.enforce_identity(answer, assistant_name)

    if identity_fixed:
        _log.info("identity guard rewrote a reply that claimed another identity")
        print("[identity guard] rewrote a reply that claimed another identity", file=sys.stderr)

    if not answer:
        answer = "Sorry, I couldn't think of an answer."

    # =========================================================
    # DISPLAY RESPONSE
    # =========================================================

    print("Lily:", answer)

    # =========================================================
    # SAVE CONVERSATION (whole turns; trimmed by token budget when prompting)
    # =========================================================

    conversation.add(user, answer)

    return {"output": answer, "exit": False}
