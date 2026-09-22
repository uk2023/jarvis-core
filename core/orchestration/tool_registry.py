from __future__ import annotations

"""LLM tool-calling: registry, dispatch, and the gating loop.

DESIGN RATIONALE (2026-09-11 discussion with UK): UK explicitly
rejected hardcoded regex for routing natural-language requests like
"pending rules dikhao" or "yeh rule reject karo" to Brain's memory-
management methods -- "Jarvis khud apne dimag se samjhe, regex nahi."
That's correct: regex here would just be Claude pre-deciding intent
on JARVIS's behalf, not JARVIS understanding anything itself.

The actual fix is standard LLM tool/function calling (see Groq's
docs, console.groq.com/docs/tool-use/overview, verified 2026-09-11):
the model itself reads the message, decides whether a tool is
relevant, and if so which one and with what arguments -- using its
own language understanding, not a pattern JARVIS's author wrote by
hand.

Architecturally this is modeled on the cortex-basal ganglia loop
(cortex proposes candidate actions; basal ganglia GATES which one
actually executes, via Go/NoGo pathways -- see e.g. Baston &
Ursino 2015, "A Biologically Inspired Computational Model of Basal
Ganglia in Action Selection"): the LLM ("cortex") PROPOSES a tool
call, but nothing executes until dispatch_tool_call() below ("basal
ganglia") gates it -- specifically, verifying a MUTATING call's
knowledge_id actually refers to a real, currently-pending/active item
before touching any real state. This is a cheap, native, zero-extra-
LLM-call check, not a second model call -- same "native before
expensive" discipline as the rest of JARVIS.

Tools available:
  - The 6 Brain methods for self-authored-rule / standing-instruction
    management (previously CLI-only: /pending_rules, /confirm_rule,
    /reject_rule, /explain_rule, /instructions, /remove_instruction).
  - browser_search: Groq's built-in, server-side web search tool
    (verified 2026-09-11 against console.groq.com/docs/tool-use/
    built-in-tools/browser-search -- supported directly by
    openai/gpt-oss-120b, JARVIS's configured model; no separate API
    key or search service needed). This is the concrete fix for
    2026-09-11 roadmap Phase 4 (knowledge-gap verification / "H2O"
    case): JARVIS can now actually check a real source instead of
    only answering from the LLM's parametric memory.
"""

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..runtime.log import log_event

READ_ONLY_TOOLS = {"list_pending_self_rules", "explain_self_rule", "list_standing_instructions", "list_contested_facts",
                    "get_recent_conversation", "explain_own_architecture", "get_conversation_history", "evaluate_own_recent_responses",
                    "list_pending_patterns"}
MUTATING_TOOLS = {"confirm_self_rule", "reject_self_rule", "remove_standing_instruction", "resolve_contested_fact",
                   "confirm_pattern", "reject_pattern", "start_remote_access", "stop_remote_access"}
# Distinct from MUTATING_TOOLS above: this doesn't touch an EXISTING
# item by knowledge_id, it creates a new one -- see save_verified_fact()
# in brain.py. UK's explicit ask (2026-09-11): searched/LLM-derived
# facts must NOT be persisted by default (fills the database with
# one-off lookups nobody asked to keep) -- only when UK explicitly
# says so ("search karke save karo", "yaad rakho"). The tool's own
# description below carries that restriction to the model; gating
# here just validates the fields are non-empty, not a knowledge_id.
WRITE_TOOLS = {"save_verified_fact", "add_relationship", "leave_message_for",
               "run_coding_task", "propose_self_feature",
               # REPO-SCALE CODING AGENT (2026-09-16, UK's merge request): distinct
               # from run_coding_task above -- that writes and iterates on ONE
               # script; this operates on a real multi-file project (existing or
               # new), using its own tool belt + approval gate. See
               # core/skills/coding_agent/ and BLUEPRINT.md.
               "run_coding_agent",
               # INDIVIDUAL WORKER HIRING (2026-09-20, root-cause pass):
               # the ordinary-chat door onto TaskLoop.stream_capability()
               # -- research/planning/editing/debug_fix as narrow, non-
               # destructive workers distinct from run_coding_agent's
               # always-full build+verify loop. See companion_tools.py's
               # run_capability_worker() docstring for the exact gap this
               # closes (previously only reachable from the Extended
               # Thinking web route, never from ordinary chat).
               "run_capability_worker",
               # TOOL REGISTRATION REQUEST (2026-09-17, UK's exact ask: "jab
               # bolu tool register karne ke liye to wo bhi fix karo"). Wraps
               # the last coding run's output as a GOVERNED DRAFT -- never
               # live on its own, same posture as propose_self_feature.
               "propose_tool_from_last_coding_run"}
READ_ONLY_TOOLS = READ_ONLY_TOOLS | {"get_relationship_tree", "list_self_proposals",
                                     "get_instruction_firings",
                                     "sandbox_overview", "list_my_uploads",
                                     # THE OTHER HALF OF UPLOADS (2026-09-21). See
                                     # companion_tools.py's read_uploaded_file() docstring --
                                     # list_my_uploads could always name an upload_id; this is
                                     # the tool that turns that ID into real content, closing
                                     # the gap that previously made the model invent a path.
                                     "read_uploaded_file",
                                     "run_self_diagnostics"}
LOCAL_TOOL_NAMES = READ_ONLY_TOOLS | MUTATING_TOOLS | WRITE_TOOLS

# DEPLOY VERIFICATION (2026-09-22). Logged once, at import time, so a
# server that's actually running this build says so in its own startup
# log without anyone needing to hit an endpoint or read a diff -- see
# backend/routes_frontend_v6.py's /api/debug/build_info for the same
# check as a live HTTP call. If a server's log never shows this line,
# that process is not running this file.
log_event("tool_registry",
          f"tool_registry loaded -- build 2026-09-22-attachment-fix-v2, "
          f"{len(LOCAL_TOOL_NAMES)} local tools incl. read_uploaded_file="
          f"{'read_uploaded_file' in LOCAL_TOOL_NAMES}", level="info")

# Expensive and side-effecting: at most ONE execution per user turn, no
# matter how many times the model proposes it (see dispatch_tool_call).
# A repo-scale agent run or a coding session costs real LLM budget and
# writes real files; a duplicate is never what UK asked for.
ONCE_PER_TURN_TOOLS = {"run_coding_agent", "run_coding_task", "propose_self_feature",
                       "propose_tool_from_last_coding_run", "run_capability_worker"}

# 3 -> 4 (2026-09-22): a "find it, then read it" chain -- list_my_uploads
# then read_uploaded_file -- is now a normal 2-tool sequence, and a single
# malformed-argument retry (e.g. a stray 'n' before the schema above
# declared it) used to be enough to crowd that whole chain out of the old
# budget of 3. One more iteration of slack costs at most one extra LLM
# round trip on the rare turn that needs it.
MAX_TOOL_ITERATIONS = 4

# DECISIVENESS (2026-09-20, root-cause pass -- UK's chat-log audit
# showed run_coding_task/run_coding_agent/run_capability_worker
# genuinely available as tools, yet turn after turn the model answered
# with an unrelated clarifying question (retirement age, team size, SLA
# percentage) instead of calling any of them for an ordinary "PDF
# reader bana do" request. The tools existing was never the whole
# problem -- the model also needs to be told plainly to prefer acting
# with sensible defaults over open-ended interviewing.
_DECISIVENESS_INSTRUCTION = (
    "\n\nACT, DON'T INTERVIEW: when UK asks for code, a project, a plan, or any action a tool "
    "here can perform, call the matching tool using his own words as the objective and sensible "
    "defaults for anything he didn't specify -- do not ask a chain of clarifying questions first. "
    "State the defaults you chose in your reply so he can correct them, rather than asking "
    "permission for each one up front. Ask at most ONE short clarifying question, and only when "
    "the request is genuinely impossible to act on without it (e.g. which of two named folders)."
)

# NO PATH GUESSING (2026-09-21, root-cause pass on UK's chat-log audit:
# turn after turn showed a confident, specific-looking filesystem path
# -- /tmp/jarvis/uploads/, /usr/share/jarvis/resources/, /root/
# Jarvis_Cloud_Work/data/sandboxes/user/anonymous/... -- that no tool
# had ever returned and that never existed. Each one READS like a real
# answer, which is exactly what made it damaging: UK trusted it, tried
# it, and it went nowhere. The pattern was never a broken filesystem;
# it was the model filling a real information gap (it genuinely has no
# path until a tool gives it one) by generating something plausible-
# sounding instead of saying so. This instruction closes the gap the
# only way that actually works: naming the specific tools that return
# REAL paths, and telling the model plainly that inventing one is
# worse than admitting it doesn't know yet.
_NO_PATH_GUESSING_INSTRUCTION = (
    "\n\nNEVER INVENT A FILESYSTEM PATH. You have no reliable sense of what exists on disk beyond "
    "what a tool result just told you -- a path that merely LOOKS plausible (/tmp/..., /usr/..., "
    "/var/..., /home/..., a sandbox path you're recalling from an earlier unrelated turn) is not "
    "evidence it exists now, for this speaker. Before stating ANY file or directory location: "
    "for an uploaded/attached file, call list_my_uploads and/or read_uploaded_file and quote the "
    "path THEY return, never one you construct yourself; for a project/sandbox directory, call "
    "sandbox_overview or the relevant coding tool rather than recalling a path from memory or from "
    "a previous conversation, which may no longer be accurate. If no tool has given you a real "
    "path yet, say plainly that you don't have one and name the tool call that would get one -- "
    "that is always more useful and more honest than a specific-sounding guess."
)

# Appended to the system prompt only for tool-enabled turns (see
# run_tool_loop below) -- UK's explicit ask: browser_search use must
# be disclosed in the reply, but the source/URL only stated if UK
# actually asks for it, not dumped every time.
_SEARCH_TRANSPARENCY_INSTRUCTION = (
    "\n\nTOOL USE DISCLOSURE: If you use browser_search to answer, briefly say in your reply "
    "that you checked current/online information for this (so it's clear it wasn't just from "
    "memory) -- but do NOT list specific URLs, article titles, or source names unless UK "
    "explicitly asks where the information came from."
)

# DATE AWARENESS (2026-09-11, UK's explicit ask): "aaj ka", "kal ka",
# "parso ka" date-relative search requests were previously left for
# the model to resolve with no actual notion of "today" -- it could
# only guess. Injecting the real current date/time lets it form a
# genuinely dated search query (e.g. "cricket news 12 September 2026")
# instead of a bare, dateless one that browser_search would answer
# with whatever's currently trending, not necessarily the requested day.
def _current_datetime_instruction() -> str:
    now = datetime.now()
    return (
        f"\n\nCURRENT DATE/TIME: {now.strftime('%A, %d %B %Y, %H:%M')} (server local time). "
        "If UK's message references a relative date (aaj/today, kal/tomorrow-or-yesterday "
        "depending on context, parso, pichle hafte, etc.), resolve it to an actual date using "
        "this before forming a browser_search query -- do not search with a bare, dateless query "
        "when a specific day was clearly meant."
    )

# DEEP RESEARCH (2026-09-11, UK's explicit ask): "broad/detailed research
# karo", "1000-5000 characters/paragraph mein batao", "vistrit jaankari
# do" signal UK wants a genuinely long-form answer, not a normal chat-
# length reply. Detected natively (zero LLM cost) so the response-
# generation call can be given a larger token budget UP FRONT, instead
# of hitting the budget wall mid-answer (see Bug 7's graceful-retry fix,
# which helps but a bigger budget from the start is strictly better).
_DEEP_RESEARCH_PATTERN = re.compile(
    r"\b(detailed research|broad(?:ly)?\s+detail|vistrit|vistaar|in\s*depth|in-depth|"
    r"\d{3,4}\s*(?:characters?|words?|shabd|akshar)|paragraph mein|lamba jawab|"
    r"khoj(?:o|kar)?\s+(?:ke\s+)?(?:bata|do)|thorough research)\b",
    re.I,
)


def is_deep_research_request(user_message: str) -> bool:
    """Pure function: does this message ask for a long-form, researched
    answer rather than a normal chat-length reply?"""
    return bool(_DEEP_RESEARCH_PATTERN.search(user_message or ""))


def build_tool_schemas() -> List[Dict[str, Any]]:
    """OpenAI-format function-calling schemas (verified against Groq's
    tool-use docs, 2026-09-11) plus Groq's built-in browser_search.
    Descriptions explicitly tell the model NOT to guess a knowledge_id
    -- it must call the matching list_* tool first and read the real
    id back, since dispatch_tool_call() below will reject a fabricated
    one anyway (cheaper for everyone if the model doesn't try)."""
    id_note = (
        " Results are returned in the same order shown to UK elsewhere "
        "(e.g. cli.py's #0, #1, #2...), so if UK refers to an item by "
        "number, that number is this array's index."
    )
    return [
        {"type": "function", "function": {
            "name": "get_recent_conversation",
            "description": (
                "Get the actual last N turns of THIS conversation (what UK said, what JARVIS replied) "
                "from JARVIS's own recorded history. ALWAYS call this for questions like 'hum kya baat "
                "kar rahe the', 'last N response do', 'apna pichla response dekh sakte ho', 'tumhe yaad "
                "hai humne kya baat ki' -- never answer these from memory/guessing, the real record is here. "
                "Each returned turn has position_from_last (1=most recent, 2=second-to-last, etc.) -- "
                "for 'second last message' or similar ordinal requests, MATCH this field directly, do not "
                "count list positions yourself."
            ),
            "parameters": {"type": "object", "properties": {
                "n": {"type": "integer", "description": "How many recent turns to return (default 5)."}
            }, "required": []},
        }},
        {"type": "function", "function": {
            "name": "get_conversation_history",
            "description": (
                "Get PERSISTED conversation history (survives restarts, unlike get_recent_conversation's "
                "session-only buffer). Use for requests further back than this session, e.g. 'last 40 "
                "messages do', or time-windowed requests like 'kal ka message do' / 'pichle 2 din mein "
                "kya baat hui' -- convert the time reference to hours_ago yourself (e.g. 'kal' -> roughly "
                "24-48, 'pichle 2 ghante' -> 2). Each returned turn has position_from_last (1=most recent, "
                "2=second-to-last, etc.) -- for ordinal requests ('second last'), MATCH this field, don't count."
            ),
            "parameters": {"type": "object", "properties": {
                "n": {"type": "integer", "description": "How many turns to return (default 20)."},
                "hours_ago": {"type": "number", "description": "Only include turns from within this many hours ago. Omit for no time limit."},
            }, "required": []},
        }},
        {"type": "function", "function": {
            "name": "evaluate_own_recent_responses",
            "description": (
                "Check JARVIS's own last N replies against what UK said right after each one, to honestly "
                "report whether each reply seems to have actually satisfied UK or was corrected. Use when "
                "UK asks JARVIS to evaluate/review its own recent responses, or asks 'kya tumhe pata hai "
                "tumne sahi jawab diya tha'."
            ),
            "parameters": {"type": "object", "properties": {
                "n": {"type": "integer", "description": "How many recent responses to check (default 3)."}
            }, "required": []},
        }},
        {"type": "function", "function": {
            "name": "explain_own_architecture",
            "description": (
                "Get JARVIS's actual, accurate architecture description -- how replies are generated "
                "(Brain decides, LLM only phrases), and what semantic/episodic/procedural/session memory "
                "actually mean for this specific system. ALWAYS call this for questions like 'kya tum "
                "JARVIS ho ya LLM', 'session aur episodic memory mein fark', 'tumhare paas kitni memory "
                "hai', 'proof do ki JARVIS ne jawab diya' -- this is fixed architectural fact, never "
                "improvise or invent an answer to these."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
        {"type": "function", "function": {
            "name": "list_pending_patterns",
            "description": (
                "List extraction patterns JARVIS wrote and sandbox-tested itself (see pattern_synthesis), "
                "awaiting UK's review. Use when UK asks about self-authored patterns/regex."
            ) + id_note,
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
        {"type": "function", "function": {
            "name": "confirm_pattern",
            "description": "Approve a self-authored extraction pattern so it runs live. Call list_pending_patterns first for the real knowledge_id.",
            "parameters": {"type": "object", "properties": {
                "knowledge_id": {"type": "string", "description": "The pattern's knowledge_id."}
            }, "required": ["knowledge_id"]},
        }},
        {"type": "function", "function": {
            "name": "reject_pattern",
            "description": "Decline a self-authored extraction pattern. Call list_pending_patterns first for the real knowledge_id.",
            "parameters": {"type": "object", "properties": {
                "knowledge_id": {"type": "string", "description": "The pattern's knowledge_id."}
            }, "required": ["knowledge_id"]},
        }},
        {"type": "function", "function": {
            "name": "start_remote_access",
            "description": (
                "Start a public HTTPS ngrok tunnel so JARVIS is reachable from outside the local "
                "network (e.g. a friend's phone). Call this when UK explicitly asks to enable remote "
                "access / share JARVIS / start ngrok -- never on your own initiative."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
        {"type": "function", "function": {
            "name": "stop_remote_access",
            "description": "Stop the ngrok tunnel started by start_remote_access. Only affects the tunnel, never the backend/frontend themselves.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
        {"type": "function", "function": {
            "name": "list_pending_self_rules",
            "description": (
                "List self-authored rules JARVIS has proposed about its own behavior that are "
                "awaiting UK's review (confirm or reject). Use when UK asks to see pending rules "
                "(e.g. 'pending rules dikhao', 'kya rule pending hai')." + id_note
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
        {"type": "function", "function": {
            "name": "explain_self_rule",
            "description": (
                "Explain WHY a specific self-authored rule was proposed -- the actual supporting "
                "reasoning evidence, not just the rule text. Use when UK asks 'why did you make "
                "this rule' / 'yeh rule kyun banaya'. Call list_pending_self_rules first if you "
                "don't already have the real knowledge_id -- never guess one."
            ),
            "parameters": {"type": "object", "properties": {
                "knowledge_id": {"type": "string", "description": "The rule's knowledge_id, from list_pending_self_rules."}
            }, "required": ["knowledge_id"]},
        }},
        {"type": "function", "function": {
            "name": "confirm_self_rule",
            "description": (
                "Confirm a pending self-authored rule so it starts influencing JARVIS's future "
                "responses. Only call when UK has clearly approved a SPECIFIC rule. Call "
                "list_pending_self_rules first if you don't already have the real knowledge_id "
                "-- never guess one."
            ),
            "parameters": {"type": "object", "properties": {
                "knowledge_id": {"type": "string", "description": "The rule's knowledge_id to confirm."}
            }, "required": ["knowledge_id"]},
        }},
        {"type": "function", "function": {
            "name": "reject_self_rule",
            "description": (
                "Reject a pending self-authored rule. JARVIS will remember the rejection and "
                "won't re-propose the identical rule later. Only call when UK has clearly "
                "declined a SPECIFIC rule. Call list_pending_self_rules first if you don't "
                "already have the real knowledge_id -- never guess one."
            ),
            "parameters": {"type": "object", "properties": {
                "knowledge_id": {"type": "string", "description": "The rule's knowledge_id to reject."}
            }, "required": ["knowledge_id"]},
        }},
        {"type": "function", "function": {
            "name": "list_standing_instructions",
            "description": (
                "List active daily standing instructions (time-triggered actions UK asked JARVIS "
                "to do every day, e.g. 'roz subah good morning bolo') and their trigger times."
                + id_note
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
        {"type": "function", "function": {
            "name": "remove_standing_instruction",
            "description": (
                "Delete a standing instruction outright. Only call when UK has clearly asked to "
                "remove a SPECIFIC instruction. Call list_standing_instructions first if you "
                "don't already have the real knowledge_id -- never guess one."
            ),
            "parameters": {"type": "object", "properties": {
                "knowledge_id": {"type": "string", "description": "The instruction's knowledge_id to remove."}
            }, "required": ["knowledge_id"]},
        }},
        {"type": "function", "function": {
            "name": "save_verified_fact",
            "description": (
                "Persist a fact to JARVIS's long-term memory. ONLY call this when UK EXPLICITLY "
                "asks to save/remember/store a specific fact -- e.g. 'search karke save kar do', "
                "'yaad rakhna ki...', 'memory mein daal do'. Do NOT call this just because you "
                "looked something up with browser_search -- most searches are for answering the "
                "immediate question only and must NOT be persisted, or memory fills with one-off "
                "lookups nobody asked to keep. If UK did not explicitly ask you to save/remember "
                "it, do not call this tool, even if the answer came from a search."
            ),
            "parameters": {"type": "object", "properties": {
                "subject": {"type": "string", "description": "What/who the fact is about, e.g. 'magnesium'."},
                "predicate": {"type": "string", "description": "The attribute/relationship, e.g. 'atomic_number'."},
                "value": {"type": "string", "description": "The fact's value, e.g. '12'."},
            }, "required": ["subject", "predicate", "value"]},
        }},
        {"type": "function", "function": {
            "name": "list_contested_facts",
            "description": (
                "List facts where a less-trusted source (e.g. an unverified guess) tried to "
                "overwrite a more-trusted one and was held back instead of silently applied. "
                "Use when UK asks about contradictions/contested facts/'conflicting info'."
            ) + id_note,
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
        {"type": "function", "function": {
            "name": "resolve_contested_fact",
            "description": (
                "Resolve a contested fact: either accept the newly-proposed value (replacing the "
                "current one) or keep the current value and dismiss the proposal. Only call when "
                "UK has clearly decided which one is right. Call list_contested_facts first if you "
                "don't already have the real knowledge_id -- never guess one."
            ),
            "parameters": {"type": "object", "properties": {
                "knowledge_id": {"type": "string", "description": "The contested fact's knowledge_id."},
                "accept_new_value": {"type": "boolean", "description": "True to accept the proposed new value, false to keep the current one."},
            }, "required": ["knowledge_id", "accept_new_value"]},
        }},
        # RELATIONSHIP TREE + MESSAGE DROP (2026-09-13). These exist so
        # the tree can be built the way UK actually talks -- "Heramb
        # mera dost hai" -- instead of only through a Python API. Adding
        # a relation is a WRITE, so it goes through the same gate as
        # save_verified_fact: fields validated, never a blind trust of
        # model-supplied arguments.
        {"type": "function", "function": {
            "name": "add_relationship",
            "description": (
                "Record that a person is related to UK -- friend/dost, girlfriend, bhai, behen, papa, "
                "mummy, colleague, etc. Call this when UK states a relationship about someone "
                "('Heramb mera dost hai', 'meri girlfriend Akanksha hai'). Only call for a "
                "relationship UK himself stated; never infer one from context."
            ),
            "parameters": {"type": "object", "properties": {
                "person": {"type": "string", "description": "The person's name, e.g. 'Heramb'."},
                "relation": {"type": "string", "description": "The relationship in UK's own words, e.g. 'dost', 'girlfriend', 'bhai'."},
                "notes": {"type": "string", "description": "Optional extra detail UK mentioned."},
            }, "required": ["person", "relation"]},
        }},
        {"type": "function", "function": {
            "name": "get_relationship_tree",
            "description": (
                "List everyone UK has recorded a relationship with, and how many people JARVIS knows. "
                "Use when UK asks who you know, about his friends/family, or 'kitne logo se "
                "interaction hota hai'."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
        {"type": "function", "function": {
            "name": "leave_message_for",
            "description": (
                "Leave a message for someone, voicemail-style. It is HELD and delivered only after "
                "that person signs in and is verified -- never to whoever merely claims to be them. "
                "Use when UK says something like 'Heramb ko bata dena ki...'."
            ),
            "parameters": {"type": "object", "properties": {
                "person": {"type": "string", "description": "Who the message is for."},
                "message": {"type": "string", "description": "The message to hold for them."},
            }, "required": ["person", "message"]},
        }},
        # CODING SANDBOX + SELF-EVOLUTION (2026-09-13). run_coding_task
        # is the only tool that iterates within a turn -- see
        # skills/codebox.py for why that is gated to coding.
        {"type": "function", "function": {
            "name": "run_coding_task",
            "description": (
                "Write and RUN code in an isolated sandbox, iterating until it works (write -> run -> "
                "read the error -> fix -> re-run). Use for a SINGLE script/file. "
                "USE THIS whenever UK asks for a program, script or .py file at all -- including "
                "casual phrasings like 'ek calculator.py do', 'yeh script likh do', 'X banao'. "
                "Asking for a file MEANS asking for working code, not a code block pasted into chat: "
                "do not answer such a request by writing the code in your reply instead of calling "
                "this tool. For a whole multi-file PROJECT, call run_coding_agent instead. "
                "Report honestly whether it ended up working."
            ),
            "parameters": {"type": "object", "properties": {
                "task": {"type": "string", "description": "What the code must do, in full."},
                "max_steps": {"type": "integer", "description": "Max fix-and-retry attempts (default 4, hard cap 12)."},
            }, "required": ["task"]},
        }},
        # REPO-SCALE CODING AGENT (2026-09-16). Separate from run_coding_task:
        # that tool is one script, write-run-fix. This tool is a whole project
        # -- existing or new -- worked on with its own tool belt (file
        # discovery, read/write/patch, search, git, tests, packaging) behind
        # an intent-based approval gate. See core/skills/coding_agent/.
        {"type": "function", "function": {
            "name": "run_coding_agent",
            "description": (
                "Work on a whole PROJECT (existing or new), not just one script: inspect files, "
                "edit/create several, run tests, fix failures, iterate until it verifies -- and "
                "optionally package the result as zip/tar.gz. Use for 'is project ko fix karo', "
                "'ek naya project banao', 'multiple files mein feature add karo', 'project ko zip/"
                "tar.gz mein do'. ALSO use this for setup/scaffolding requests that don't name a "
                "specific file -- 'sandbox mein jaake ek file create kar do', 'chalo is project pe "
                "kaam karte hain, pehle directory setup karo', 'ek naya folder banao aur usme...'. "
                "These are still real filesystem actions UK wants performed, not just discussed -- "
                "call this tool rather than describing in words what you would do. Destructive or "
                "high-risk steps (deleting files, git commit) are held for your explicit yes and "
                "reported back, not run silently. This ALWAYS runs the complete build-and-verify "
                "loop and writes real files. If UK only wants research, a plan, one targeted edit, "
                "or a diagnose-and-fix pass -- NOT a full build yet -- use run_capability_worker "
                "instead, with the matching capability. Prefer the narrowest tool that actually "
                "matches what UK asked for."
            ),
            "parameters": {"type": "object", "properties": {
                "objective": {"type": "string", "description": "What the finished project/change must do, in full."},
                "repo_path": {"type": "string", "description": "Path to an EXISTING project to work on. Omit to start a fresh project in a new sandbox."},
                "max_iterations": {"type": "integer", "description": "Max plan/execute/verify/fix cycles (default 6, hard cap 20)."},
            }, "required": ["objective"]},
        }},
        # INDIVIDUAL WORKER HIRING (2026-09-20). Distinct from both tools
        # above: run_coding_task/run_coding_agent always execute; this
        # tool hires exactly the capability the request actually calls
        # for, including the ones that deliberately do NOT touch the
        # sandbox at all.
        {"type": "function", "function": {
            "name": "run_capability_worker",
            "description": (
                "Hire ONE narrow worker for a coding/project request, instead of always running "
                "the full build. capability='research': think something through, report findings, "
                "nothing built. capability='planning': UK says 'plan bana do'/'pehle plan karo'/"
                "'architecture design karo' -- produces a real plan and STOPS, no files written, no "
                "code run. capability='editing': ONE targeted change to something that already "
                "exists. capability='debug_fix': a diagnose-fix-confirm cycle on a specific failure. "
                "capability='full_build': ONLY when UK has clearly said he wants the actual working "
                "thing built now. CRITICAL: when UK asks for a plan or research, calling this with "
                "capability='planning'/'research' IS the correct and complete way to satisfy the "
                "request -- do not ask a string of clarifying questions first (team size, SLA "
                "percentages, unrelated details) unless one specific detail is genuinely blocking. "
                "Take UK's own words as the objective, choose sensible defaults for anything "
                "unstated, and call this tool; explain the defaults you chose in your reply "
                "afterward rather than asking permission for each one up front."
            ),
            "parameters": {"type": "object", "properties": {
                "objective": {"type": "string", "description": "What UK actually asked for, in his own terms."},
                "capability": {"type": "string", "enum": ["research", "planning", "editing", "debug_fix", "full_build"],
                               "description": "Which narrow worker to hire. Default to 'planning' if genuinely unsure, never silently 'full_build'."},
                "repo_path": {"type": "string", "description": "Existing project path to continue, if any."},
                "max_steps": {"type": "integer", "description": "Step cap for this worker (default 6)."},
            }, "required": ["objective", "capability"]},
        }},
        {"type": "function", "function": {
            "name": "propose_tool_from_last_coding_run",
            "description": (
                "Register the most recently coded/built thing as a governed tool proposal. Use "
                "when UK says something like 'isko tool bana do', 'ab ise apna tool bana lo', "
                "'is PDF reader ko native tool bna lo', 'iske liye tool register karo' -- i.e. "
                "asking to turn a script from a run_coding_agent/run_coding_task session into a "
                "JARVIS capability. This does NOT activate anything live -- it drafts a governed "
                "proposal (same mechanism as propose_self_feature) and returns its id plus the "
                "exact CLI command UK runs to approve+activate it. Never say you cannot do this at "
                "all; the honest answer is that the DRAFT step is yours, the ACTIVATION step is "
                "UK's, by design."
            ),
            "parameters": {"type": "object", "properties": {
                "feature_name": {"type": "string", "description": "Short name for the tool, e.g. 'pdf_reader'."},
                "rationale": {"type": "string", "description": "Why this should become a standing tool."},
            }, "required": ["feature_name", "rationale"]},
        }},
        {"type": "function", "function": {
            "name": "propose_self_feature",
            "description": (
                "Propose a NEW capability for YOURSELF (JARVIS's own architecture/behavior) -- "
                "write the code, validate it in your own evolution sandbox, and log it for UK. "
                "Use ONLY when YOU noticed a recurring need in YOUR OWN functioning that you "
                "cannot currently meet -- this is self-modification, not project work. "
                "NEVER use this for something UK asked you to build for HIM (a PDF reader, a "
                "website, a script, any project he described) -- that is run_coding_task or "
                "run_coding_agent, regardless of how the request is worded (even if UK says "
                "\"design an architecture\" or \"build a capability\" -- if the THING BEING BUILT "
                "is for him to use, not a change to how JARVIS itself works, this is the wrong "
                "tool). A real observed failure: UK asked for a PDF-reader project and this tool "
                "fired instead of run_coding_agent, so JARVIS reported the request as \"noted, "
                "but needs developer review\" instead of actually building anything -- exactly "
                "the confusion this note exists to prevent. You can never install a self-feature "
                "yourself -- UK adopts it. Anything touching the shell, network, filesystem or "
                "imports will be held for his approval regardless of how confident you are."
            ),
            "parameters": {"type": "object", "properties": {
                "feature_name": {"type": "string", "description": "Short name for the capability."},
                "code": {"type": "string", "description": "Complete, standalone Python for it."},
                "rationale": {"type": "string", "description": "Why you need it -- what you could not do without it."},
                "confidence": {"type": "number", "description": "0.0-1.0, how sure you are this is worth adding."},
            }, "required": ["feature_name", "code", "rationale"]},
        }},
        {"type": "function", "function": {
            "name": "list_self_proposals",
            "description": (
                "List the features you have proposed for yourself and their status -- including which "
                "ones are waiting on UK's approval. Use when UK asks about your evolution, self-"
                "improvement, pending features, or what you have been building."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
        {"type": "function", "function": {
            "name": "get_instruction_firings",
            "description": (
                "Show when your standing instructions actually fired, with outcomes. Use when UK asks "
                "whether a scheduled instruction ran, or about reminder/instruction history."
            ),
            "parameters": {"type": "object", "properties": {
                "limit": {"type": "integer", "description": "How many recent firings (default 20)."},
            }, "required": []},
        }},
        {"type": "function", "function": {
            "name": "sandbox_overview",
            "description": (
                "Show the sandbox layout: which roles/users have working directories, how much is in "
                "them, and the current package-install policy. Use when UK asks about sandboxes, "
                "isolation, or whether installs are allowed."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
        {"type": "function", "function": {
            "name": "run_self_diagnostics",
            "description": (
                "Check your own health: known crash causes, resource spikes, and other real problems "
                "this project has hit before, each with either a fix you can name or an honest "
                "'this is new, I don't know the fix yet'. Use when UK asks what's wrong, whether you "
                "are okay, why something crashed, or asks you to diagnose yourself. Never invent a "
                "cause or a fix that is not in this report -- if it says 'unknown', say so."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
        {"type": "function", "function": {
            "name": "list_my_uploads",
            "description": (
                "List files the current speaker has uploaded into their own sandbox, each with its "
                "real upload_id, real path, and when it was modified. Use when they ask about a file "
                "they attached or what you have from them, OR whenever they reference an attachment "
                "by filename/'yeh file'/'is file me' without giving you an ID -- call this FIRST to "
                "find the matching upload_id from the real list, then call read_uploaded_file with "
                "it. You only ever see this person's uploads, never another user's. NEVER state a "
                "file's location without having gotten it from this tool or read_uploaded_file -- "
                "guessing a plausible-looking path (e.g. /tmp/..., /usr/share/..., /var/lib/...) is "
                "always wrong, because uploads only ever live at the exact paths these tools return."
            ),
            "parameters": {"type": "object", "properties": {
                "n": {"type": "integer", "description": "Optional -- only the N most recent uploads. Omit for all of them."},
            }, "required": []},
        }},
        {"type": "function", "function": {
            "name": "read_uploaded_file",
            "description": (
                "Read the ACTUAL content of a file the current speaker uploaded, by its real "
                "upload_id (get this from list_my_uploads if you don't already have it from this "
                "conversation). Returns the real absolute path plus file content for text/code/"
                "structured files, or an honest note plus the real path for anything else (PDF, "
                "image, audio, archive) that can't be read as text directly. This is the ONLY way "
                "to see what is actually inside an attachment -- call it whenever the person asks "
                "you to read, summarize, extract from, or otherwise use a file they attached, "
                "instead of answering from the filename alone or from a path you have not gotten "
                "from a tool. If the upload_id doesn't match anything, the result includes their "
                "real upload list so you can match by filename instead of inventing an ID or a path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "upload_id": {"type": "string", "description": "The real upload_id from list_my_uploads or from earlier in this conversation."},
                    "filename": {"type": "string", "description": "Optional -- narrow to one file by name if the upload contains several (e.g. an extracted archive)."},
                },
                "required": ["upload_id"],
            },
        }},
        # Groq built-in, server-side web search -- see module docstring.
        # No local dispatch needed: Groq executes this itself and
        # returns the synthesized, cited answer directly in
        # message.content (see run_tool_loop()'s handling below).
        {"type": "browser_search"},
    ]


def dispatch_tool_call(brain: Any, name: str, args: Dict[str, Any], search_used_this_turn: bool = False) -> Dict[str, Any]:
    """THE GATE (see module docstring). Validates before executing;
    never trusts the model's arguments blindly for a mutating/write call."""
    if name not in LOCAL_TOOL_NAMES:
        return {"error": f"unknown or non-local tool: {name}"}
    method = getattr(brain, name, None)
    if not callable(method):
        return {"error": f"tool '{name}' is not available on this Brain instance"}

    # ONCE-PER-TURN GATE for expensive, side-effecting tools (2026-09-16,
    # from UK's runtime log: three run_coding_agent calls fired in ONE
    # turn -- each would have spawned a full repo-scale agent run, with
    # its own LLM spend and its own file writes, for a single user
    # request). MAX_TOOL_ITERATIONS lets the model call again after
    # seeing a result, which is correct for cheap read tools and wrong
    # for these. The first result is returned again rather than erroring,
    # so the model still gets a usable answer instead of being confused
    # into a third attempt.
    if name in ONCE_PER_TURN_TOOLS:
        already = getattr(brain, "_tools_run_this_turn", None)
        if already is None:
            already = {}
            brain._tools_run_this_turn = already
        if name in already:
            log_event("tool_registry",
                      f"suppressed duplicate '{name}' call in one turn -- returning first result",
                      level="info")
            return {**already[name],
                    "note": f"'{name}' already ran this turn; this is that same result, "
                             f"not a second run."}

    if name in MUTATING_TOOLS and name not in ("start_remote_access", "stop_remote_access"):
        knowledge_id = args.get("knowledge_id")
        if not knowledge_id:
            return {"error": "knowledge_id is required"}
        if name in ("confirm_self_rule", "reject_self_rule"):
            valid_ids = {r.get("knowledge_id") for r in brain.list_pending_self_rules()}
        elif name == "resolve_contested_fact":
            valid_ids = {r.get("knowledge_id") for r in brain.list_contested_facts()}
        elif name in ("confirm_pattern", "reject_pattern"):
            valid_ids = {r.get("knowledge_id") for r in brain.list_pending_patterns()}
        else:  # remove_standing_instruction
            valid_ids = {r.get("knowledge_id") for r in brain.list_standing_instructions()}
        if knowledge_id not in valid_ids:
            return {
                "error": (
                    f"knowledge_id '{knowledge_id}' does not match any current item. "
                    "Call the matching list_* tool first to get real ids -- do not guess."
                )
            }

    # SCOPED TO save_verified_fact ONLY (fixed 2026-09-16 from UK's runtime
    # log). This block used to run for every name in WRITE_TOOLS -- but
    # subject/predicate/value are save_verified_fact's OWN fields; no other
    # write tool has them. So run_coding_agent, run_coding_task,
    # add_relationship, leave_message_for and propose_self_feature were all
    # rejected with "subject, predicate and value are all required" BEFORE
    # their method was ever called. UK's log shows the exact symptom: three
    # run_coding_agent calls in one turn (the model retrying a call that kept
    # erroring) and then a generic "mujhe status pata nahi" reply, because the
    # agent genuinely never ran and there was no real result to report.
    if name == "save_verified_fact":
        subject, predicate, value = args.get("subject"), args.get("predicate"), args.get("value")
        if not subject or not predicate or value in (None, ""):
            return {"error": "subject, predicate and value are all required"}
        if any(len(str(v)) > 300 for v in (subject, predicate, value)):
            return {"error": "subject/predicate/value must each be under 300 characters"}
        # source_type honesty (see core/memory/semantic_memory.py's
        # provenance system): "verified" only if browser_search
        # actually ran earlier THIS turn -- if the model is saving
        # something from its own parametric memory on request, that's
        # still unverified, just now durable instead of ephemeral.
        args = {**args, "source_type": "verified" if search_used_this_turn else "llm_unverified"}

    try:
        result = method(**args) if args else method()
    except Exception as exc:
        log_event("tool_registry", f"tool '{name}' execution failed: {exc}", level="warning")
        return {"error": str(exc)}
    if name in ONCE_PER_TURN_TOOLS and isinstance(result, dict):
        getattr(brain, "_tools_run_this_turn", {})[name] = result
    return result


def run_tool_loop(brain: Any, system_prompt: str, user_message: str,
                   max_iterations: int = MAX_TOOL_ITERATIONS) -> Optional[str]:
    """Runs the propose -> gate -> execute -> re-evaluate loop until the
    model returns a final answer (no more tool_calls) or iterations run
    out. Returns None if tool-calling isn't usable this turn at all
    (caller -- see Brain's response-generation block -- must fall back
    to the existing plain generate() path unchanged); returns None
    (not a stub string) if the loop exhausts its iterations without a
    final answer too, for the same reason.

    IMPORTANT (openai/gpt-oss-120b doesn't support parallel tool use,
    verified against Groq's docs 2026-09-11): a compound instruction
    like "X search karo aur save karo" cannot be one tool call that
    does both -- browser_search (built-in, resolves fully server-side
    in a single completion) has to be followed by a SEPARATE local
    save_verified_fact call in a LATER iteration, once the model has
    seen the search result. So a built-in tool firing does NOT end
    the loop here the way a genuinely final answer does -- the model
    gets one more turn to decide if a local follow-up action is still
    needed, nudged by a synthetic system message rather than assumed
    silently either way.

    The full tool-call trace is recorded on brain.last_tool_call_trace
    (bounded, most-recent-turn only) so monitor.py / a future API
    endpoint can show exactly which tools fired and why -- UK's
    explicit ask that autonomous actions stay traceable, not a black
    box."""
    llm = getattr(brain, "llm", None)
    if llm is None or not hasattr(llm, "generate_with_tools"):
        return None

    deep_research = is_deep_research_request(user_message)
    # Bigger token budget UP FRONT for deep-research requests (2026-09-11,
    # UK's explicit ask) instead of hitting the wall mid-answer.
    max_tokens = 2048 if deep_research else 1024

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt + _DECISIVENESS_INSTRUCTION
                                       + _NO_PATH_GUESSING_INSTRUCTION
                                       + _SEARCH_TRANSPARENCY_INSTRUCTION + _current_datetime_instruction()},
        {"role": "user", "content": user_message},
    ]
    tools = build_tool_schemas()
    trace: List[Dict[str, Any]] = []
    search_used_this_turn = False
    # Fresh per turn -- this is what makes ONCE_PER_TURN_TOOLS mean
    # "once per user request", not "once per process".
    brain._tools_run_this_turn = {}
    # HONEST DEGRADATION SIGNAL (2026-09-20, root-cause pass): reset
    # before attempting, same discipline as last_tool_call_trace just
    # above. Set True ONLY on the "generate_with_tools returned None"
    # path below -- a genuine provider/connectivity failure, not "the
    # model looked and decided no tool was needed" (that path returns
    # real content, never None). brain.py's plain-generate() fallback
    # reads this to tell the model honestly that it cannot act this
    # turn, instead of silently losing tool access and improvising a
    # reply that looks like normal conversation.
    brain.last_tool_loop_failed = False

    for iteration in range(max(1, max_iterations)):
        message = llm.generate_with_tools(messages=messages, tools=tools, tool_choice="auto", max_tokens=max_tokens, reasoning_effort="low")
        if message is None:
            brain.last_tool_call_trace = trace
            brain.last_tool_loop_failed = True
            return None

        tool_calls = message.get("tool_calls") or []
        executed = message.get("executed_tools")

        if tool_calls:
            messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls})
            for call in tool_calls:
                fn = call.get("function", {}) or {}
                name = fn.get("name")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                result = dispatch_tool_call(brain, name, args, search_used_this_turn=search_used_this_turn)
                trace.append({"name": name, "arguments": args, "result": result})
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id"),
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
            continue

        if executed:
            # Built-in tool (browser_search) resolved server-side.
            # STRUCTURED capture (2026-09-11, UK's explicit ask): keep
            # the actual title/url/content/score records JARVIS itself
            # can inspect and reason about later -- not just a
            # truncated str() blob of whatever Groq returned.
            search_used_this_turn = True
            structured_results = []
            try:
                for tool_exec in (executed if isinstance(executed, list) else [executed]):
                    if isinstance(tool_exec, dict):
                        results = tool_exec.get("search_results") or {}
                        for item in (results.get("results") or []) if isinstance(results, dict) else []:
                            structured_results.append({
                                "title": item.get("title"), "url": item.get("url"),
                                "content": item.get("content"), "score": item.get("score"),
                            })
            except Exception:
                structured_results = []
            trace.append({
                "builtin_tool": True,
                "executed_tools_summary": str(executed)[:500],
                "search_results": structured_results,
            })
            if iteration < max_iterations - 1:
                messages.append({"role": "assistant", "content": message.get("content")})
                messages.append({
                    "role": "system",
                    "content": (
                        "If the original request also explicitly asked you to save/remember this "
                        "fact, call save_verified_fact now with the right subject/predicate/value. "
                        "Otherwise, just repeat your answer above as the final response -- do not "
                        "search again."
                    ),
                })
                continue
            # Out of iterations to safely follow up -- return what we have.
            brain.last_tool_call_trace = trace
            return _finalize_search_response(message.get("content"), structured_results, deep_research)

        # Genuinely final: no tool call, no built-in tool fired.
        content = message.get("content")
        brain.last_tool_call_trace = trace
        return str(content).strip() if content else None

    brain.last_tool_call_trace = trace
    return None


def _finalize_search_response(llm_content: Optional[str], structured_results: List[Dict[str, Any]], deep_research: bool) -> Optional[str]:
    """THE architecture UK explicitly asked for: for a normal search
    answer, the model's own short synthesis (message.content) is fine
    as-is -- Groq's browser_search already does real synthesis+
    citation in one call, and re-doing that ourselves would just be
    duplicate work. But for a DEEP-RESEARCH request specifically ("1000-
    5000 characters", "vistrit jaankari", "broad detailed research"),
    generating that much length THROUGH the LLM burns a large number of
    OUTPUT tokens for text that's mostly just restating what the search
    already found. Instead: keep the model's own content as a short
    intro/framing (cheap, a few sentences), then have JARVIS's own code
    assemble the actual body directly from the raw structured_results
    Groq already returned -- the LLM is not asked to regenerate or
    paraphrase that part at all, so length no longer costs proportional
    output tokens. This is "LLM sirf structure/intro de, JARVIS data
    khud chipkaye" applied concretely to search results specifically
    (the general version -- EVERY reply routed through a second
    constrained brief-style pass -- remains a bigger, separate piece of
    work, not done here)."""
    content = str(llm_content).strip() if llm_content else ""
    if not deep_research or not structured_results:
        return content or None
    intro = content or "Maine iske baare mein online search kiya, yeh mila:"
    body_parts = [intro, ""]
    for i, item in enumerate(structured_results[:8], start=1):
        title = item.get("title") or f"Source {i}"
        url = item.get("url") or ""
        snippet = (item.get("content") or "").strip()
        if not snippet:
            continue
        body_parts.append(f"**{i}. {title}**" + (f" ({url})" if url else ""))
        body_parts.append(snippet)
        body_parts.append("")
    return "\n".join(body_parts).strip()
