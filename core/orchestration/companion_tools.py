from __future__ import annotations

"""Brain capabilities added 2026-09-13, kept in a mixin so brain.py
itself is not touched more than the one line that inherits it.

Four things UK asked for:

  1. RELATIONSHIP TOOLS -- so the tree can be built by talking
     ("Heramb mera dost hai"), not only through a Python API.

  2. MESSAGE DROP -- voicemail for someone, held until they verify.

  3. STANDING-INSTRUCTION AUDIT -- UK: "standing instruction silently
     hit ho jata hai, UI ya trace ya kahin bhi iska record nahi aata".
     Every firing is now recorded with a timestamp and reason, so
     there is an actual place to look. A scheduled action that runs
     invisibly is indistinguishable from one that never ran, which is
     exactly why this was hard to trust.

  4. SEARCH CONFIRMATION -- UK: JARVIS should decide when to go to the
     internet, and when it is unsure, ASK rather than either guessing
     or silently searching. Pairs with information_need.py: that
     decides WHERE an answer lives; this handles the borderline case
     where going out to the web is a judgement call.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..runtime.log import log_event

_AUDIT_DB = Path("data/instruction_audit.db")


def _audit_conn() -> sqlite3.Connection:
    _AUDIT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_AUDIT_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS instruction_firings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            instruction_id TEXT,
            instruction_text TEXT,
            trigger_type TEXT,
            fired_at REAL NOT NULL,
            outcome TEXT,
            detail TEXT
        )
    """)
    return conn


def record_instruction_firing(instruction_id: str, instruction_text: str,
                              trigger_type: str, outcome: str,
                              detail: Optional[str] = None) -> None:
    """Called whenever a standing instruction actually fires. Silent
    failure here is acceptable (an audit write must never break the
    action it is recording) but it is logged, so a missing trail is
    itself visible."""
    try:
        with _audit_conn() as conn:
            conn.execute(
                "INSERT INTO instruction_firings (instruction_id, instruction_text, trigger_type,"
                " fired_at, outcome, detail) VALUES (?, ?, ?, ?, ?, ?)",
                (instruction_id, instruction_text, trigger_type, time.time(), outcome, detail),
            )
            conn.commit()
        log_event("instructions", f"standing instruction fired: {instruction_text[:60]} -> {outcome}", level="info")
    except Exception as exc:
        log_event("instructions", f"could not record instruction firing (audit trail incomplete): {exc}", level="warning")


def get_instruction_firings(limit: int = 20) -> List[Dict[str, Any]]:
    try:
        with _audit_conn() as conn:
            rows = conn.execute(
                "SELECT instruction_id, instruction_text, trigger_type, fired_at, outcome, detail"
                " FROM instruction_firings ORDER BY fired_at DESC LIMIT ?", (max(1, int(limit)),)
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


# Going to the web is worth confirming when the question is answerable
# EITHER from the model's own knowledge or from a live source, and the
# two could disagree. A settled historical fact needs no search; a
# stock price needs no confirmation (it simply cannot be answered
# without one). The interesting middle is where asking is cheapest.
_SETTLED_MARKERS = ("history", "itihas", "kab bana", "who invented", "kisne banaya",
                    "definition", "matlab kya", "kya hota hai", "explain", "samjhao")
_MUST_SEARCH_MARKERS = ("price", "rate", "bhav", "stock", "nifty", "sensex", "weather",
                        "mausam", "score", "news", "khabar", "aaj ka", "today's",
                        # DEVANAGARI (added 2026-09-15, from UK's own chat log): the
                        # checks above only matched Latin-script text, so "निफ़्टी"
                        # typed in Devanagari missed EVERY rule here -- including
                        # decide_information_need()'s own world_live classification,
                        # which also came back as the generic "language" source for
                        # the same input. Until that deeper NLU gap is fixed for
                        # Devanagari generally, this list at least catches the
                        # highest-frequency terms UK actually hit.
                        "निफ़्टी", "निफ्टी", "सेंसेक्स", "मौसम", "भाव", "स्टॉक", "खबर")

# Turns about JARVIS itself, UK, or the people around him are never a
# web question -- checked BEFORE the generic fallthrough below, or
# "kis baare mein baat kar rahe the" and "UJJWAL kaun hai" (both
# already-known facts) end up offering a web search anyway, which is
# exactly what UK's log showed on 29 of 144 turns.
_PERSONAL_MARKERS = ("tum", "tumhe", "tumhara", "tumhari", "mujhe", "mera", "meri", "mere",
                     "aap", "aapka", "apna", "yaad", "jante", "janta", "jaanta", "naam",
                     "creator", "kaun ho", "who are you", "kis baare mein", "kya baat",
                     "kar rahe the", "kaise ho", "how are you")

# The confirm branch is for turns that GENUINELY smell time-sensitive --
# not the catch-all for anything uncertain. UK's log showed "2*2=?" and
# "how are you" both ending in "web se check karun?" because the old
# default sent every unmatched turn here.
_MAYBE_STALE_MARKERS = ("kaunsa behtar", "compare", " vs ", "latest", "naya", "new",
                        "price", "kitne ka", "release", "version")


def should_confirm_search(user_input: str, information_need: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Decide: search outright, ask first, or don't search.

    Returns {"action": "search"|"confirm"|"no_search", "reason": str}.
    """
    text = (user_input or "").lower()
    need = (information_need or {}).get("source")

    if any(m in text for m in _MUST_SEARCH_MARKERS) or need == "world_live":
        return {"action": "search",
                "reason": "Yeh live data hai -- iska jawab bina source ke dena guess hoga, isliye seedha search."}

    if any(m in text for m in _SETTLED_MARKERS):
        return {"action": "no_search",
                "reason": "Yeh settled/conceptual sawaal hai -- ismein search se kuch nahi badlega."}

    # Explicit instruction always wins over JARVIS's own judgement.
    if any(m in text for m in ("search karo", "internet", "web se", "dekh kar batao", "google")):
        return {"action": "search", "reason": "UK ne khud search karne ko kaha."}

    if need in ("semantic", "episodic", "rules", "self_state", "procedural"):
        return {"action": "no_search",
                "reason": f"Iska jawab {need} memory ka hai, internet ka nahi."}

    # PERSONAL/SELF-REFERENTIAL -- checked before the fallthrough. UK's
    # log: "UJJWAL kaun hai?" (already answered), "kis baare mein baat
    # kar rahe the?", "how are you jarvis" all offered a web search
    # despite being about JARVIS, UK, or their own conversation -- none
    # of which a web search can answer.
    if any(m in text for m in _PERSONAL_MARKERS):
        return {"action": "no_search",
                "reason": "Yeh hamare baare mein hai -- iska jawab memory mein hai, web pe nahi."}

    # DEFAULT IS NO_SEARCH, NOT CONFIRM (fixed 2026-09-15 -- this exact
    # fix was made once earlier and lost when the working tree was
    # reverted; UK's fresh chat log showed the regression directly: 29
    # of 144 turns ended in an unprompted "web se check karun?",
    # including on "2*2 = ?" and "how are you jarvis"). Confirming is
    # now reserved for turns that actually smell time-sensitive;
    # everything else gets a plain answer with no search offer at all.
    if any(m in text for m in _MAYBE_STALE_MARKERS):
        return {"action": "confirm",
                "reason": "Time-sensitive ho sakta hai -- ek line mein poochna theek hai."}

    return {"action": "no_search",
            "reason": "Isme kuch live nahi hai -- jo pata hai wahi seedha bolo."}


class CompanionToolsMixin:
    """Mixed into Brain. Every method here is dispatchable as a tool."""

    # ---------------------------------------------------- relationships
    def add_relationship(self, person: str, relation: str, notes: Optional[str] = None) -> Dict[str, Any]:
        from ..identity.relationships import add_relationship as _add, who_is
        if not (person or "").strip() or not (relation or "").strip():
            return {"error": "person and relation are both required"}
        existing = who_is(person)
        rel_id = _add(person=person, relation=relation, notes=notes)
        return {
            "success": True, "id": rel_id, "person": person.strip(), "relation": relation.strip().lower(),
            "note": (f"Pehle se '{existing['relation']}' recorded tha -- ab yeh bhi jud gaya."
                     if existing else "Naya relation record ho gaya."),
        }

    def get_relationship_tree(self) -> Dict[str, Any]:
        from ..identity.relationships import get_relationship_tree as _tree, known_people_count
        return {"tree": _tree(), "stats": known_people_count()}

    def leave_message_for(self, person: str, message: str) -> Dict[str, Any]:
        from ..identity.relationships import leave_message, who_is
        if not (person or "").strip() or not (message or "").strip():
            return {"error": "person and message are both required"}
        msg_id = leave_message(from_username="uk", for_person=person, message=message)
        known = who_is(person)
        return {
            "success": True, "id": msg_id, "for": person.strip(),
            "delivery": (
                "Unke sign in karke verify hone par pahuncha dunga."
                if known and known.get("linked_username")
                else "Abhi unka account link nahi hai -- jab woh signup karke verify honge, tab milega."
            ),
        }

    # --------------------------------------------- coding + evolution
    def run_coding_task(self, task: str, max_steps: int = 4) -> Dict[str, Any]:
        """The ONLY multi-step path in JARVIS -- see skills/codebox.py."""
        from ..skills.codebox import run_coding_session
        if not (task or "").strip():
            return {"error": "task is required"}
        try:
            return run_coding_session(
                self.llm.generate_response,
                task=task,
                system_prompt="You are JARVIS, writing code for UK.",
                max_steps=max_steps,
            )
        except Exception as exc:
            return {"error": f"coding session failed: {exc}", "solved": False}

    def propose_tool_from_last_coding_run(self, feature_name: str, rationale: str) -> Dict[str, Any]:
        """LLM-callable (2026-09-17, UK's exact request: "jab bolu tool
        register karne ke liye to wo bhi fix karo"). Before this, "ab
        is pdf reader ko native tool bna lo" had NO honest path
        forward -- companion_tools.activate_coding_tool exists but is
        deliberately not LLM-callable (activating code into a live
        registry is a human decision), so the only truthful answer was
        "is samay yeh capability mere paas nahi hai" -- which read as
        "I can never do this" when the real answer was "I can draft
        the proposal; only the activation step needs your approval".
        This closes that gap without weakening the approval gate: it
        wraps the most recent coding run's main file as a GOVERNED
        DRAFT (self_evolution.propose_feature, same mechanism
        propose_self_feature already uses) and returns the proposal id
        plus the exact next step, instead of a proposal silently
        appearing or a flat "can't do that"."""
        agent = getattr(self, "_last_coding_agent", None)
        task = getattr(self, "_last_coding_task", None)
        if agent is None or task is None:
            # WORDING FIXED 2026-09-19 (UK's real chat log: JARVIS
            # repeated, verbatim, across ~15 turns, some variant of
            # "pehle run_coding_task ya run_coding_agent chalaiye" --
            # phrased as an instruction for UK to type a terminal
            # command himself. Both are JARVIS's OWN tools (see their
            # schemas in tool_registry.py: "call this tool", never
            # "tell the user to run this") -- this error string is
            # very likely what the model was paraphrasing from, and
            # the old wording ("pehle kuch banwao") was ambiguous
            # enough to read either way. Made unambiguous: this is an
            # instruction to JARVIS's OWN NEXT TOOL CALL in the SAME
            # turn, never something to hand back to UK as a command to
            # run himself.
            return {"error": (
                "No coding run recorded in this session yet. Call "
                "run_coding_task or run_coding_agent YOURSELF, right now, "
                "in this same turn, to actually build the thing -- do NOT "
                "tell UK to run a command; he cannot invoke JARVIS's "
                "internal tools from outside the chat. Once that call "
                "succeeds, call propose_tool_from_last_coding_run again."
            )}
        try:
            workspace_root = agent.workspace.root
            candidates = sorted(
                (p for p in workspace_root.rglob("*.py") if p.is_file()),
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
        except Exception as exc:
            return {"error": f"workspace read nahi ho paaya: {exc}"}
        if not candidates:
            return {"error": "is coding run ne koi .py file nahi banayi -- tool banane ke liye pehle koi script chahiye."}
        try:
            code = candidates[0].read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return {"error": f"file padhi nahi gayi: {exc}"}
        try:
            from ..evolution.self_evolution import propose_feature
            result = propose_feature(feature_name=feature_name, code=code, rationale=rationale, confidence=0.6)
        except Exception as exc:
            return {"error": f"proposal nahi ban paaya: {exc}"}
        if result.get("status") == "refused":
            return {"error": result.get("reason", "proposal refused")}
        result["next_step"] = (
            f"Proposal ban gaya (id={result.get('id')}), source file: {candidates[0].name}. "
            f"Ise LIVE tool banane ke liye explicit approval chahiye -- CLI mein "
            f"/activate_tool {result.get('id')} <entry_point_function_name> chalao."
        )
        return result

    def run_coding_agent(self, objective: str, repo_path: Optional[str] = None,
                         max_iterations: int = 6) -> Dict[str, Any]:
        """REPO-SCALE coding agent (2026-09-16, UK's merge request). Distinct
        from run_coding_task above: that writes/iterates on ONE script;
        this inspects, edits and verifies a whole project through its own
        tool belt + approval gate (core/skills/coding_agent/). If a step
        needs UK's explicit yes, this returns status WAITING_APPROVAL with
        `pending_approval` describing exactly what and why, rather than
        silently proceeding OR silently refusing."""
        if not (objective or "").strip():
            return {"error": "objective is required"}
        try:
            from ..skills.coding_agent import CodingAgent
            # CONTINUITY (2026-09-17, UK's exact complaint: "ab try karo",
            # "library install karke phir try karo", "continue" each
            # started a BRAND NEW empty sandbox -- repo_path=None meant a
            # fresh CodingAgent() picked a fresh random workdir every
            # single call, so nothing from the PDF reader attempt two
            # messages ago was ever still there to continue. When the
            # caller doesn't name a specific project, default to the
            # SAME workspace the last coding-agent run in this session
            # used, so a follow-up in the same conversation actually
            # resumes where it left off instead of starting from an
            # empty folder that looks identical to "nothing happened".
            if not repo_path and getattr(self, "_last_coding_agent", None) is not None:
                repo_path = str(self._last_coding_agent.workspace.root)
            agent = CodingAgent(
                self.llm.generate_response, role=getattr(self, "role", "user"),
                repo_path=repo_path, max_iterations=max_iterations,
                extra_tools=list(getattr(self, "_activated_coding_tools", {}).values()),
            )
            task = agent.run(objective)
            # kept on the brain instance (not persisted -- see BLUEPRINT.md
            # Phase 10) purely so a follow-up "haan karo" in the same
            # process can call resume_coding_agent() below.
            self._last_coding_agent = agent
            self._last_coding_task = task
            self._feed_coding_run_to_learning(task)
            return self._coding_agent_result(task)
        except Exception as exc:
            return {"error": f"coding agent failed: {exc}", "status": "FAILED"}

    @staticmethod
    def _coding_agent_result(task: Any) -> Dict[str, Any]:
        """The dict the LLM actually sees after a coding-agent run.

        UK's runtime log (2026-09-16) showed JARVIS replying "mujhe status
        pata nahi" after a coding request -- the tool had errored, but the
        failure was also SHAPED badly: a raw as_dict() is a large nested
        blob with no plain statement of what happened, so the model had
        nothing quotable and invented a hedge instead. This returns an
        explicit, human-readable `summary` FIRST, plus the honest detail
        underneath, so the model can only report what actually occurred.
        """
        full = task.as_dict()
        status = full.get("status")
        files = sorted({(o.get("tool_call") or {}).get("arguments", {}).get("path")
                        for o in full.get("observations", [])
                        if (o.get("tool_call") or {}).get("arguments", {}).get("path")})
        verif = full.get("verifications") or []
        last = verif[-1] if verif else None

        if status == "WAITING_APPROVAL":
            pa = full.get("pending_approval") or {}
            call = pa.get("call", {})
            summary = (f"Ruka hua hai -- aapki permission chahiye: {call.get('tool_name')}"
                        f"({call.get('arguments')}). Wajah: {pa.get('reason')}. "
                        f"Aage badhne ke liye /approve_coding_step yes ya no bolo. "
                        f"Sandbox path: {full.get('repo_path')}.")
        elif status == "BLOCKED":
            # Set by the nothing-happened guard in agent._verify_and_continue.
            # Its result_summary already states the real reason in plain
            # Hinglish -- pass it straight through rather than re-wording it
            # into something vaguer.
            summary = (full.get("result_summary") or "Kuch nahi hua -- koi tool chala hi nahi.") + \
                      f" Sandbox path: {full.get('repo_path')}."
        elif status == "COMPLETED":
            summary = (f"Ho gaya. {len(files)} file(s) likhi/badli: {', '.join(files) or '(koi nahi)'}. "
                        f"Verification: {last['method']} PASS. "
                        f"Sandbox path: {full.get('repo_path')}." if last else
                        f"Ho gaya. Sandbox path: {full.get('repo_path')}.")
        else:
            why = "; ".join(full.get("errors", [])[-2:]) or "koi specific error record nahi hua"
            vtxt = (f"{last['method']} FAIL" if last else "verification chala hi nahi")
            summary = (f"Poora nahi hua ({status}). Verification: {vtxt}. "
                        f"Jo hua: {why}. {len(files)} file(s) touch hui: "
                        f"{', '.join(files) or '(koi nahi)'}. "
                        f"Sandbox path: {full.get('repo_path')}.")

        return {
            "summary": summary,
            "status": status,
            "files_touched": files,
            "workspace": full.get("repo_path"),
            "artifacts": full.get("artifacts"),
            "verification": last,
            "errors": full.get("errors"),
            "iterations": full.get("iteration"),
            "task_id": full.get("id"),
            "instruction_to_model": (
                "Report ONLY what `summary` says. Do not claim anything succeeded that "
                "`status` does not say succeeded, and do not invent file names, test "
                "results or package paths that are not listed here. `summary` always "
                "states the real sandbox path this task used -- if UK asks where "
                "something was created/saved/is located, quote that path exactly; "
                "never guess a path, never say you don't know where it is."
            ),
        }

    def _feed_coding_run_to_learning(self, task: Any) -> None:
        """REUSE, not a new learning system: shapes the finished task into
        the same experience dict LearningCoordinator.learn() already
        accepts, so repeated successful coding-agent runs accumulate into
        governed skill proposals exactly like any other JARVIS action --
        see core/skills/self_extension.record_run_as_experience() and
        core/learning/learning_coordinator.py's existing skill_learner
        wiring. A single run never auto-registers anything; only
        SkillLearner's own repetition threshold (default: 3 successes)
        ever produces a proposal, and only UK approving + activating it
        (see activate_coding_tool below) makes it live."""
        if getattr(self, "learning", None) is None or task.status not in (
            "COMPLETED", "FAILED"):
            return
        try:
            from ..skills.self_extension import record_run_as_experience
            self.learning.learn(record_run_as_experience(task))
        except Exception as exc:
            log_event("coding_agent", f"could not feed run to learning: {exc}", level="warning")

    def activate_coding_tool(self, proposal_id: str, entry_point: str) -> Dict[str, Any]:
        """Turns an ALREADY-APPROVED self_evolution proposal (from
        propose_self_feature or the coding agent's own propose_new_tool
        step) into a live tool in the most recent coding-agent run's
        ToolRegistry. Deliberately NOT an LLM-callable tool -- reaching
        this requires an explicit human/CLI call, same posture as
        decide_self_proposal. See core/skills/self_extension.py."""
        agent = getattr(self, "_last_coding_agent", None)
        if agent is None:
            return {"error": "no coding-agent run in this session to activate a tool into"}
        try:
            from ..evolution.self_evolution import list_proposals
            from ..skills.self_extension import activate_tool
        except Exception as exc:
            return {"error": f"self-extension unavailable: {exc}"}
        matches = [p for p in list_proposals(limit=500) if p.get("id") == proposal_id]
        if not matches:
            return {"error": f"no proposal with id {proposal_id}"}
        result = activate_tool(matches[0], entry_point=entry_point, target_registry=agent.registry)
        if result.get("ok"):
            # Persisted on the Brain instance (not yet across process
            # restarts -- see BLUEPRINT.md persistence note) so the NEXT
            # run_coding_agent() call gets this tool for free.
            spec = agent.registry.get(result["tool_name"])
            if spec is not None:
                if not hasattr(self, "_activated_coding_tools"):
                    self._activated_coding_tools = {}
                self._activated_coding_tools[spec.name] = spec
        return result

    def resume_coding_agent(self, approve: bool) -> Dict[str, Any]:
        """Continues the most recent run_coding_agent() call past an
        approval gate. NOT exposed as an LLM tool -- deciding APPROVE vs
        DENY on JARVIS's own initiative would defeat the gate's purpose;
        only UK's explicit yes/no (via CLI/UI) reaches this."""
        agent = getattr(self, "_last_coding_agent", None)
        task = getattr(self, "_last_coding_task", None)
        if agent is None or task is None:
            return {"error": "no coding-agent task is waiting on approval"}
        task = agent.resume(task, approve=approve)
        self._last_coding_task = task
        self._feed_coding_run_to_learning(task)
        return self._coding_agent_result(task)

    # ------------------------------------------------------------------
    # INDIVIDUAL WORKER HIRING (2026-09-20, root-cause pass -- UK's chat
    # log audit)
    #
    # THE GAP THIS CLOSES: core/orchestration/task_loop.py's
    # TaskLoop.stream_capability() -- research / planning / editing /
    # debug_fix / full_build as INDIVIDUALLY hireable workers -- has
    # existed since 2026-09-18/19 and is fully tested (test_e2e_
    # scenarios.py), but the ONLY place that ever called it was
    # backend/routes_codebox.py's Extended-Thinking SSE route, gated
    # behind `req.mode != "off"`. Ordinary chat (the tool-calling loop
    # in tool_registry.py's run_tool_loop, which is what UK's actual
    # transcript goes through) had no way to reach it at all -- it
    # only ever had run_coding_task (one script) and run_coding_agent
    # (always the FULL repo-scale build+verify loop, never just
    # "research this" or "plan this, don't build yet"). That is the
    # concrete, verifiable cause of "jarvis khud coding agent se kaam
    # nahi karwa pa raha", "planning module ko seedha call nahi kar
    # sakte" (JARVIS's own words, 2026-09-20 13:00 in UK's log) and
    # the pattern of endless clarifying questions in place of just
    # doing the narrow, minimal-required thing UK asked for.
    #
    # This method is the ordinary-chat door onto the SAME TaskLoop,
    # reusing every existing safety property instead of re-deriving
    # them: stream_capability()'s own refusal to silently default to
    # full_build on an unrecognized capability, should_invoke_coding_
    # agent() as the second gate on full_build (identical to Extended
    # Thinking's gate -- see routes_codebox.py), and format_relevant_
    # context_text() (just factored out of routes_codebox.py, see
    # conversation_continuity.py) so this call is exactly as context-
    # aware as an Extended-Thinking turn, not a second, poorer path.
    def run_capability_worker(self, objective: str, capability: str = "planning",
                              repo_path: Optional[str] = None, max_steps: int = 6) -> Dict[str, Any]:
        """Hire ONE narrow capability -- 'research', 'planning', 'editing',
        'debug_fix', or 'full_build' -- instead of always paying for
        (or always avoiding) the complete build+verify loop. See the
        tool's own schema in tool_registry.py for the model-facing
        usage rule: full_build only when UK is genuinely ready for code
        to be written and run; every other case uses the narrower,
        cheaper, non-destructive capability that actually matches what
        was asked.
        """
        objective = (objective or "").strip()
        if not objective:
            return {"error": "objective is required"}
        capability = (capability or "planning").strip().lower()
        valid = {"research", "planning", "editing", "debug_fix", "full_build"}
        if capability not in valid:
            return {"error": f"capability must be one of {sorted(valid)}, got {capability!r}"}

        context = ""
        if hasattr(self, "conversation_continuity"):
            try:
                context = self.conversation_continuity.format_relevant_context_text()
            except Exception as exc:
                log_event("companion_tools", f"continuity context unavailable: {exc}", level="warning")

        # SECOND GATE (identical to routes_codebox.py's Extended
        # Thinking route -- UK's own requirement, section 7: "coding
        # agent tabhi call ho jab conversation intelligence bole ki
        # user chahta hai now code", not the LLM's classification
        # alone). Keeping this identical here is what stops ordinary
        # chat and Extended Thinking from diverging on the exact same
        # safety question the way TaskLoop's context did before.
        downgraded_from = None
        if capability == "full_build" and hasattr(self, "conversation_continuity"):
            try:
                if not self.conversation_continuity.should_invoke_coding_agent():
                    downgraded_from = "full_build"
                    capability = "planning"
            except Exception as exc:
                log_event("companion_tools", f"continuity gate unavailable: {exc}", level="warning")

        try:
            from .task_loop import TaskLoop
            import functools
            # TOKEN LEDGER PURPOSE TAG: every call this worker makes gets
            # attributed to "capability_worker:<capability>" in
            # token_management.py's per-purpose breakdown (UK's spec),
            # via functools.partial so TaskLoop's own internal call sites
            # -- which don't know about purpose tagging -- don't need any
            # changes themselves.
            tagged_generate = functools.partial(self.llm.generate_response, purpose=f"capability_worker:{capability}")
            loop = TaskLoop(
                tagged_generate, brain=self,
                role=getattr(self, "role", "user"),
                is_verified=getattr(self, "is_verified", False),
                effort="medium", context=context,
            )
            events: List[Dict[str, Any]] = list(loop.stream_capability(objective, capability, max_steps=max_steps))
        except Exception as exc:
            return {"error": f"capability worker failed: {exc}", "capability": capability}

        # CLI/monitor visibility (2026-09-19 pattern, reused not
        # reinvented -- see routes_codebox.py's identical assignment):
        # this is the one shared field cli.py's "4e. EXTENDED THINKING"
        # panel reads, so a chat-tool-originated worker run shows up
        # there too instead of only web-Extended-Thinking runs.
        try:
            self.last_thinking_decision = {
                "think": True, "mode": f"chat_tool_worker:{capability}",
                "reason": f"run_capability_worker invoked '{capability}' directly from a chat tool call.",
            }
        except Exception:
            pass

        return self._summarize_capability_run(capability, events, downgraded_from)

    @staticmethod
    def _summarize_capability_run(capability: str, events: List[Dict[str, Any]],
                                  downgraded_from: Optional[str]) -> Dict[str, Any]:
        """Turns stream_capability()'s raw event list into the same kind
        of plain, honest `summary` + `instruction_to_model` shape
        _coding_agent_result() already gives run_coding_agent -- so the
        model can only report what actually happened, never invent
        success the events don't support (same principle task_loop.py's
        own _conclude() states in its docstring)."""
        aborted = next((e for e in events if e.get("type") == "aborted"), None)
        if aborted:
            summary = f"Ruk gaya: {aborted.get('reason', 'budget/limit khatam')}."
            return {"summary": summary, "capability": capability, "status": "ABORTED",
                    "events": events, "instruction_to_model": "Report only this; do not claim work happened."}

        complete = next((e for e in events if e.get("type") == "capability_complete"), None)
        if complete is not None:
            content = complete.get("content")
            note = f" (downgraded from {downgraded_from}, coding agent was not authorized yet)" if downgraded_from else ""
            summary = f"{capability.capitalize()} complete{note}."
            return {"summary": summary, "capability": capability, "status": "COMPLETE",
                    "result": content, "events": events,
                    "instruction_to_model": (
                        "This is research/planning output ONLY -- no code was written or run. "
                        "Say so plainly if UK expected code; report `result` as findings/plan, not as a finished build."
                    )}

        # editing / debug_fix / full_build all end via the ordinary
        # step-stream shape (stage/stage_start/done/error events).
        done = next((e for e in events if e.get("type") == "done"), None)
        error = next((e for e in events if e.get("type") == "error"), None)
        if error:
            return {"summary": f"Error: {error.get('error')}", "capability": capability,
                    "status": "FAILED", "events": events,
                    "instruction_to_model": "Report this failure honestly; do not claim it worked."}
        if done:
            result = done.get("result") or {}
            note = f" (downgraded from {downgraded_from})" if downgraded_from else ""
            summary = str(result.get("conclusion") or f"{capability} finished{note}.")
            return {"summary": summary, "capability": capability, "status": "DONE",
                    "result": result, "events": events,
                    "instruction_to_model": "Report exactly what `summary`/`result.conclusion` says, nothing more."}

        return {"summary": f"{capability} ran but produced no conclusive event -- treat as incomplete.",
                "capability": capability, "status": "UNKNOWN", "events": events,
                "instruction_to_model": "Do not claim success; tell UK this needs a retry."}

    def propose_self_feature(self, feature_name: str, code: str,
                             rationale: str, confidence: float = 0.5) -> Dict[str, Any]:
        from ..evolution.self_evolution import propose_feature
        if not (feature_name or "").strip() or not (code or "").strip():
            return {"error": "feature_name and code are both required"}
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except Exception:
            confidence = 0.5
        return propose_feature(feature_name, code, rationale or "", confidence)

    def list_self_proposals(self) -> Dict[str, Any]:
        from ..evolution.self_evolution import evolution_status, list_proposals
        status = evolution_status()
        return {
            "status": status,
            "proposals": [
                {k: p.get(k) for k in ("id", "feature_name", "status", "confidence",
                                       "rationale", "approval_reasons", "created_at")}
                for p in list_proposals(limit=20)
            ],
        }

    def decide_self_proposal(self, proposal_id: str, approve: bool) -> Dict[str, Any]:
        """Deliberately NOT exposed as an LLM tool -- approving its own
        proposals is the one decision JARVIS must never make. Callable
        from the CLI/UI by UK only."""
        from ..evolution.self_evolution import decide_proposal
        return decide_proposal(proposal_id, approve=approve, decided_by="UK")

    # ------------------------------------------------------ step goals
    def run_goal_stepwise(self, goal: str, role: str = "user",
                          is_verified: bool = False, max_steps: int = 6) -> Dict[str, Any]:
        """Multi-step goal execution -- owner/co-owner only. Not exposed
        as an LLM tool: UK asks for it explicitly, so the CLI/UI calls
        this rather than letting the model start a multi-call run on its
        own judgement."""
        from .step_goals import run_goal_steps
        if not (goal or "").strip():
            return {"error": "goal is required"}
        return run_goal_steps(
            self.llm.generate_response, goal=goal, role=role,
            is_verified=is_verified, max_steps=max_steps, brain=self,
        )




    def sandbox_overview(self) -> Dict[str, Any]:
        from ..skills.sandbox_policy import sandbox_overview as _overview
        return _overview()

    def run_self_diagnostics(self) -> Dict[str, Any]:
        """Read-only -- JARVIS reports what it finds, never auto-fixes
        during a normal conversation. Applying a remedy is a deliberate
        owner/co-owner action (CLI's /diagnose fix, or the HTTP
        POST /diagnose/fix route), never something a chat turn triggers
        on its own."""
        from ..runtime.diagnostics import run_diagnostics
        return run_diagnostics(auto_fix=False)

    def list_my_uploads(self, n: Optional[int] = None, **_ignored: Any) -> Dict[str, Any]:
        """Only the current speaker's uploads -- scoped by their own
        sandbox, so there is no path to another user's files.

        n (2026-09-22): the model has repeatedly called this with a
        pagination-style arg (n=5, n=10, limit=...) that the original
        no-params schema didn't declare -- each one errored, burned an
        LLM tool-call round trip, and cost a slot out of the small
        per-turn tool-iteration budget for no reason. Accepted here
        (and any other stray kwarg silently ignored via **_ignored)
        so that habit costs nothing instead of stealing a round trip
        that read_uploaded_file needed."""
        from ..skills.upload_guard import list_uploads
        speaker = getattr(self, "current_speaker", None) or {}
        uploads = list_uploads(role=speaker.get("role", "user"), username=speaker.get("username"))
        # Most recent first when trimming -- an arbitrary "n" almost
        # always means "the one(s) I just did", not the oldest.
        uploads = sorted(uploads, key=lambda u: u.get("modified", ""), reverse=True)
        if isinstance(n, int) and n > 0:
            uploads = uploads[:n]
        return {"uploads": uploads}

    def read_uploaded_file(self, upload_id: str, filename: Optional[str] = None) -> Dict[str, Any]:
        """THE OTHER HALF of the upload feature (2026-09-21 root-cause
        pass, UK's chat-log audit: "attach nahi hota... JARVIS bas
        directory hallucinate karta hai"). list_my_uploads could always
        list an upload's ID; nothing could turn that ID into actual
        content for a tool or a reply, so a turn like "yeh file dekho:
        ticket.pdf" had a real file sitting in the speaker's sandbox
        the whole time with no path from that sentence to it -- and
        the model, left to fill the gap, invented a plausible-sounding
        path (/tmp/jarvis/uploads/, /usr/share/jarvis/resources/, ...)
        that accept_upload() never wrote to.

        Scoped exactly like list_my_uploads: only the current speaker's
        own sandbox is ever searched, via upload_guard's single shared
        path-resolution helper -- this method never constructs a path
        itself, so it cannot drift into guessing one either."""
        from ..skills.upload_guard import read_uploaded_file as _read
        speaker = getattr(self, "current_speaker", None) or {}
        return _read(upload_id, role=speaker.get("role", "user"),
                    username=speaker.get("username"), filename=filename)

    # --------------------------------------------- standing instructions
    def get_instruction_firings(self, limit: int = 20) -> Dict[str, Any]:
        firings = get_instruction_firings(limit)
        return {
            "firings": firings,
            "count": len(firings),
            "note": ("Abhi tak koi standing instruction fire nahi hui (ya audit trail shuru hone se "
                     "pehle hui thi)." if not firings else None),
        }
