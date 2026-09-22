#!/usr/bin/env python3
"""JARVIS LLM PROVIDER MONITOR (2026-09-20, root-cause pass).

Read-only. Independent of monitor.py's process (matches its own
"second terminal" design -- see blueprint.txt section 7) but reads the
SAME kind of IPC state file, specifically the `llm_provider_quota`
telemetry that core/orchestration/llm_bridge.py's GroqEngine now
publishes after EVERY real HTTP attempt (see
GroqEngine._record_key_telemetry / _publish_telemetry in llm_bridge.py)
-- both the ordinary generate_response() path and the
generate_with_tools() path used by run_coding_agent /
run_capability_worker / the coding agent, since both funnel through
GroqEngine._post_chat_completion, the single choke point that records
telemetry.

This file is deliberately NOT an independent quota calculator. It
never estimates, guesses, or fabricates a number -- every figure here
came from a real Groq response header or a real request Jarvis
actually made. Where Groq has not published something, this shows
"NOT PUBLISHED" rather than inventing a placeholder.

Usage:
    python3 llm_monitor.py                  # curses dashboard, live
    python3 llm_monitor.py --ui panel       # one-line panel (for tmux status bars)
    python3 llm_monitor.py --plain          # no curses, ANSI-clear polling loop
    python3 llm_monitor.py --state PATH     # explicit IPC file instead of autodetect
"""
from __future__ import annotations

import argparse
import curses
import json
import os
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_INTERVAL = 1.0
STALE_AFTER = 60.0
IPC_DEFAULT = os.path.join(tempfile.gettempdir(), "jarvis_state.ipc")
LEGACY_NAMES = ("llm_quota_state.json", "llm_provider_state.json", "llm_provider_engine_state.json")


def now() -> float:
    return time.time()


def read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return None


def num(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return default if v is None else float(v)
    except (TypeError, ValueError):
        return default


def integer(v: Any, default: int = 0) -> int:
    try:
        return default if v is None else int(v)
    except (TypeError, ValueError):
        return default


def first(d: Any, *names: str, default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    for name in names:
        if d.get(name) is not None:
            return d[name]
    return default


def fmt_num(v: Any) -> str:
    if v is None:
        return "NOT PUBLISHED"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def fmt_time(ts: Any) -> str:
    t = num(ts)
    if t is None:
        return "NOT PUBLISHED"
    left = max(0.0, t - now())
    if left < 1:
        return "now"
    if left < 60:
        return f"{left:.1f}s"
    if left < 3600:
        return f"{left/60:.1f}m"
    return f"{left/3600:.1f}h"


def fmt_age(ts: Any, fallback_path: Optional[str] = None) -> str:
    t = num(ts)
    if t is None and fallback_path:
        try:
            t = os.path.getmtime(fallback_path)
        except OSError:
            pass
    if t is None:
        return "unknown"
    age = max(0.0, now() - t)
    if age < 60:
        return f"{age:.1f}s"
    if age < 3600:
        return f"{age/60:.1f}m"
    return f"{age/3600:.1f}h"


def resolve_state_path(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    env = os.getenv("JARVIS_LLM_STATE") or os.getenv("JARVIS_STATE_IPC")
    if env:
        return env
    candidates = [IPC_DEFAULT]
    base = os.path.dirname(os.path.abspath(__file__))
    for name in LEGACY_NAMES:
        candidates.extend((os.path.join(base, "runtime", name), os.path.join(os.getcwd(), "runtime", name)))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return IPC_DEFAULT


def unwrap(raw: Any, path: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None, {"source": path}
    metadata = {"source": path}
    for key in ("updated_at", "timestamp", "generated_at", "pid", "runtime"):
        if raw.get(key) is not None:
            metadata[key] = raw[key]
    quota = raw.get("llm_provider_quota")
    if isinstance(quota, dict):
        metadata["wrapper"] = "llm_provider_quota"
        return quota, metadata
    return raw, metadata


def providers(snapshot: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    raw = first(snapshot, "providers", "provider", "llm_providers", "provider_quota", "quotas", default={})
    out: List[Tuple[str, Dict[str, Any]]] = []
    if isinstance(raw, dict):
        for name, value in raw.items():
            if isinstance(value, dict):
                out.append((str(name), value))
            elif isinstance(value, list):
                out.append((str(name), {"keys": value}))
    elif isinstance(raw, list):
        for i, value in enumerate(raw, 1):
            if isinstance(value, dict):
                name = first(value, "name", "provider", "provider_name", "id", default=f"provider-{i}")
                out.append((str(name), value))
    return out


def keys(provider: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = first(provider, "keys", "api_keys", "key_states", "key_usage", default=[])
    if isinstance(raw, dict):
        out = []
        for i, (name, value) in enumerate(raw.items(), 1):
            item = dict(value) if isinstance(value, dict) else {"value": value}
            item.setdefault("key_index", i)
            item.setdefault("name", str(name))
            out.append(item)
        return out
    if isinstance(raw, list):
        out = []
        for i, value in enumerate(raw, 1):
            item = dict(value) if isinstance(value, dict) else {"value": value}
            item.setdefault("key_index", i)
            out.append(item)
        return out
    return []


def nested_limit(key: Dict[str, Any], name: str, rem_names: Tuple[str, ...], lim_names: Tuple[str, ...], reset_names: Tuple[str, ...]) -> Dict[str, Any]:
    raw = key.get(name)
    if isinstance(raw, dict):
        return {"remaining": first(raw, "remaining", *rem_names), "limit": first(raw, "limit", *lim_names), "reset_at": first(raw, "reset_at", *reset_names)}
    return {"remaining": first(key, *rem_names), "limit": first(key, *lim_names), "reset_at": first(key, *reset_names)}


def request_info(key: Dict[str, Any]) -> Dict[str, Any]:
    raw = key.get("last_request")
    if not isinstance(raw, dict):
        raw = key
    return {
        "estimated": first(raw, "estimated_tokens", "last_estimated_tokens", "estimated_usage", default=first(key, "estimated_tokens", "last_estimated_tokens")),
        "prompt": first(raw, "actual_prompt_tokens", "prompt_tokens", "input_tokens"),
        "output": first(raw, "actual_output_tokens", "completion_tokens", "output_tokens"),
        "total": first(raw, "actual_total_tokens", "total_tokens", "usage_total_tokens"),
        "request_id": first(raw, "request_id", "id", default=first(key, "last_request_id", "request_id")),
        "model": first(raw, "model", default=first(key, "last_model", "model")),
        "status": first(raw, "status_code", "http_status", default=first(key, "last_http_status", "http_status", "status_code")),
        "latency": first(raw, "latency_seconds", "latency", default=first(key, "latency_seconds", "latency")),
    }


def selection(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    candidates = [snapshot.get("selection_state"), snapshot.get("selection"), snapshot.get("selection_trace"), snapshot.get("provider_selection")]
    overall = snapshot.get("overall")
    if isinstance(overall, dict):
        candidates += [overall.get("selection_state"), overall.get("selection"), overall.get("selection_trace")]
    for value in candidates:
        if isinstance(value, dict):
            return value
    return {}


def available(key: Dict[str, Any]) -> bool:
    cd = num(first(key, "cooldown_until", "cooldown_end"))
    if cd is not None and cd > now():
        return False
    status = str(first(key, "status", "state", default="AVAILABLE")).upper()
    return status not in {"DOWN", "FAILED", "UNAVAILABLE", "EXCLUDED"}


def summary(ps: List[Tuple[str, Dict[str, Any]]]) -> Dict[str, Any]:
    all_keys = [(p, k) for p, provider in ps for k in keys(provider)]
    live_cap = live_used = live_rem = metadata = 0
    active = cooldown = failed = used = 0
    for _, key in all_keys:
        used += integer(first(key, "requests_used", "used", "requests", default=0))
        failed += 1 if integer(first(key, "failures", "failure_count", "errors", default=0)) else 0
        cd = num(first(key, "cooldown_until", "cooldown_end"))
        if cd is not None and cd > now(): cooldown += 1
        else: active += 1
        lim = integer(first(key, "live_limit_requests", "live_limit", default=0))
        rem = integer(first(key, "live_remaining_requests", "live_remaining", default=0))
        if lim > 0:
            metadata += 1
            live_cap += lim
            live_rem += max(0, rem)
            live_used += max(0, lim - rem)
    up = sum(1 for _, p in ps if bool(first(p, "available", "is_available", "online", "up", default=True)))
    return {"providers": len(ps), "up": up, "keys": len(all_keys), "active": active, "cooldown": cooldown, "failed": failed, "used": used, "cap": live_cap, "rem": live_rem, "used_live": live_used, "metadata": metadata}


def lines_for(raw: Any, path: str) -> List[str]:
    snapshot, meta = unwrap(raw, path)
    if snapshot is None:
        return ["JARVIS LLM PROVIDER MONITOR", "INVALID/UNREADABLE STATE"]
    ps = providers(snapshot)
    timestamp = meta.get("updated_at", snapshot.get("updated_at"))
    age = fmt_age(timestamp, path)
    ts = num(timestamp)
    runtime = "LIVE" if ts is None or now() - ts <= STALE_AFTER else f"STALE {age}"
    s = summary(ps)
    out = [f"JARVIS LLM PROVIDER MONITOR   runtime={runtime}", f"  source={path}", f"  state updated {age} ago", "", "GLOBAL PROVIDER BALANCE", f"  providers={s['up']}/{s['providers']} up   keys={s['keys']}   active={s['active']}   cooldown={s['cooldown']}   failed={s['failed']}"]
    if s["cap"]:
        pct = s["used_live"] / s["cap"] * 100.0
        out.append(f"  live-window capacity {s['used_live']}/{s['cap']}  {pct:.1f}%   remaining={s['rem']}   metadata={s['metadata']}/{s['keys']}")
    else:
        out.append(f"  live-window capacity NOT PUBLISHED   metadata={s['metadata']}/{s['keys']}")
    out += [f"  cumulative requests={s['used']}", "", "SELECTION"]
    sel = selection(snapshot)
    est = first(sel, "current_request_estimate", "estimated_tokens", "request_estimate", "required_tokens")
    if isinstance(est, dict):
        est_input = first(
            est,
            "estimated_input_tokens",
            "input_tokens",
            default=None,
        )
        est_output = first(
            est,
            "estimated_output_tokens",
            "output_tokens",
            "max_tokens",
            default=None,
        )
        est_total = first(
            est,
            "estimated_total_tokens",
            "total_tokens",
            default=None,
        )

        if est_total is None and (
            est_input is not None or est_output is not None
        ):
            try:
                est_total = (
                    int(est_input or 0)
                    + int(est_output or 0)
                )
            except (TypeError, ValueError):
                est_total = None

        out.append(
            "  current request estimate: "
            f"input={fmt_num(est_input)} "
            f"output={fmt_num(est_output)} "
            f"total={fmt_num(est_total)}"
        )
    else:
        out.append(
            f"  current request estimate: "
            f"{fmt_num(est)} tokens"
        )

    eligible = first(
        sel,
        "available_keys",
        "eligible_keys",
        "eligible",
        "candidates",
        default=[],
    )

    if isinstance(eligible, dict):
        eligible = list(eligible.values())

    if isinstance(eligible, list) and eligible:
        labels = []

        for item in eligible:
            if isinstance(item, dict):
                provider = item.get("provider", "?")
                key_index = item.get(
                    "key_index",
                    item.get("index", "?"),
                )
                utilization = item.get(
                    "utilization_percent"
                )

                label = (
                    f"{provider}#{key_index}"
                )

                if utilization is not None:
                    label += (
                        f"({utilization:.1f}%)"
                        if isinstance(utilization, (int, float))
                        else f"({utilization})"
                    )

                labels.append(label)
            else:
                labels.append(str(item))

        out.append(
            "  eligible: " + " ".join(labels)
        )
    else:
        out.append("  eligible: NONE")
    excluded = first(sel, "excluded_keys", "excluded", "rejected", default=[])
    out.append(f"  excluded: {json.dumps(excluded, ensure_ascii=False) if excluded else 'NONE'}")
    last_p = first(sel, "selected_provider", "last_provider", default=first(snapshot, "last_provider"))
    last_k = first(sel, "selected_key_index", "last_key_index", "selected_key", default=first(snapshot, "last_key_index"))
    out.append(f"  LAST SELECTED: {last_p or 'N/A'} / key #{last_k}" if last_k is not None else f"  LAST SELECTED: {last_p or 'N/A'}")
    out += ["", "TOP 10 AVAILABLE KEYS — REAL CAPACITY"]
    ranked = []
    for pname, provider in ps:
        for key in keys(provider):
            if not available(key):
                continue
            tpm = nested_limit(key, "tpm", ("tpm_remaining", "remaining_tpm", "live_remaining_tokens", "remaining_tokens"), ("tpm_limit", "tokens_per_minute_limit", "live_limit_tokens", "token_limit"), ("tpm_reset_at", "tokens_reset_at", "live_tokens_reset_at"))
            rem = integer(first(key, "live_remaining_requests", "live_remaining", default=0))
            score = num(tpm["remaining"])
            ranked.append((score if score is not None else -1, rem, pname, key))
    ranked.sort(key=lambda x: (-x[0], -x[1], integer(first(x[3], "key_index", default=0))))
    for rank, (_, _, pname, key) in enumerate(ranked[:10], 1):
        tpm = nested_limit(key, "tpm", ("tpm_remaining", "remaining_tpm", "live_remaining_tokens", "remaining_tokens"), ("tpm_limit", "tokens_per_minute_limit", "live_limit_tokens", "token_limit"), ("tpm_reset_at", "tokens_reset_at", "live_tokens_reset_at"))
        lim = first(key, "live_limit_requests", "live_limit")
        rem = first(key, "live_remaining_requests", "live_remaining")
        out.append(f"  {rank:>2}. {pname} key #{integer(first(key,'key_index',default=rank)):<2}  TPM={fmt_num(tpm['remaining'])}/{fmt_num(tpm['limit'])}  RPM={fmt_num(rem)}/{fmt_num(lim)}  status={first(key,'status',default='AVAILABLE')}")
    if not ranked:
        out.append("  no available keys published")
    out += ["", "PROVIDERS"]
    for pname, provider in ps:
        pstatus = str(first(provider, "status", "state", default="UP")).upper()
        pavail = bool(first(provider, "available", "is_available", "online", "up", default=True))
        ks = keys(provider)
        out.append(f"  {pname:<14} keys={len(ks)}  STATUS={pstatus} AVAILABLE={pavail}  model={first(provider,'model',default=snapshot.get('model','NOT PUBLISHED'))}")
        for key in ks:
            idx = integer(first(key, "key_index", "index", "slot", default=0))
            status = first(key, "status", "state", default="UNKNOWN")
            tpm = nested_limit(key, "tpm", ("tpm_remaining", "remaining_tpm", "live_remaining_tokens", "remaining_tokens"), ("tpm_limit", "tokens_per_minute_limit", "live_limit_tokens", "token_limit"), ("tpm_reset_at", "tokens_reset_at", "live_tokens_reset_at"))
            rpd = nested_limit(key, "rpd", ("rpd_remaining", "daily_remaining", "requests_remaining_daily", "live_rpd_remaining"), ("rpd_limit", "daily_limit", "requests_per_day_limit", "live_rpd_limit"), ("rpd_reset_at", "daily_reset_at", "live_rpd_reset_at"))
            rpm = nested_limit(key, "rpm", ("rpm_remaining", "requests_remaining", "live_remaining_requests", "live_remaining"), ("rpm_limit", "requests_per_minute_limit", "live_limit_requests", "live_limit"), ("rpm_reset_at", "requests_reset_at", "live_reset_at"))
            out.append(f"    KEY #{idx}  STATUS={status}  capacity={fmt_num(key.get('capacity'))} used={fmt_num(key.get('requests_used'))} remaining={fmt_num(key.get('estimated_remaining'))} utilization={fmt_num(key.get('utilization_percent'))}%")
            out.append(f"      TPM: {fmt_num(tpm['remaining'])}/{fmt_num(tpm['limit'])} reset={fmt_time(tpm['reset_at'])}")
            out.append(f"      RPD: {fmt_num(rpd['remaining'])}/{fmt_num(rpd['limit'])} reset={fmt_time(rpd['reset_at'])}")
            out.append(f"      RPM: {fmt_num(rpm['remaining'])}/{fmt_num(rpm['limit'])} reset={fmt_time(rpm['reset_at'])}")
            out.append(f"      cooldown={fmt_time(key.get('cooldown_until'))}  balance-reset={fmt_time(key.get('balance_reset_at'))}  exhaustion={fmt_time(key.get('expected_exhaustion_at'))}")
            req = request_info(key)
            out.append("      LAST REQUEST")
            out.append(f"        estimated: {fmt_num(req['estimated'])} tokens")
            out.append(f"        actual prompt: {fmt_num(req['prompt'])}")
            out.append(f"        actual output: {fmt_num(req['output'])}")
            out.append(f"        actual total: {fmt_num(req['total'])}")
            out.append(f"        request id: {req['request_id'] or 'NOT PUBLISHED'}")
            out.append(f"        model: {req['model'] or provider.get('model') or snapshot.get('model') or 'NOT PUBLISHED'}")
            out.append(f"        HTTP status: {fmt_num(req['status'])}")
            out.append(f"        latency: {fmt_num(req['latency'])}s  avg={fmt_num(key.get('avg_latency_seconds'))}s")
            out.append(f"      requests={fmt_num(key.get('requests_used'))} attempts={fmt_num(key.get('requests_attempted'))} success={fmt_num(key.get('successes', key.get('success_count')))} failed={fmt_num(key.get('failures'))}")
            if key.get('last_error'):
                out.append(f"      last error: {key['last_error']}")
    overall = snapshot.get("overall")
    if isinstance(overall, dict):
        out += ["", "ENGINE OVERALL"]
        for name, value in overall.items():
            if name == "selection_state":
                continue
            out.append(f"  {name}: {value}")
    out += ["", "NOTE: monitor is read-only; it never changes provider/key selection."]
    return out


def panel(snapshot: Any, path: str, width: int = 140) -> str:
    snap, _ = unwrap(snapshot, path)
    if not snap:
        return " JARVIS LLM | WAITING FOR LIVE IPC "
    ps = providers(snap)
    groq = next((p for n, p in ps if n.lower() == "groq"), None)
    if not groq:
        return " JARVIS LLM | GROQ NOT PUBLISHED "
    sel = selection(snap)
    parts = [" JARVIS LLM", "GROQ", f"keys={len(keys(groq))}"]
    sk = first(sel, "selected_key_index", "last_key_index")
    if sk is not None:
        parts.append(f"selected=#{sk}")
    for k in keys(groq):
        rem = first(k, "live_remaining_requests", "live_remaining", default="?")
        lim = first(k, "live_limit_requests", "live_limit", default="?")
        parts.append(f"#{integer(first(k,'key_index',default=0))}:{rem}/{lim}")
    text = " | ".join(parts)
    return text if len(text) <= width else text[:max(1, width-1)] + "…"


def run_plain(path: str, interval: float, ui: str) -> int:
    try:
        while True:
            raw = read_json(path)
            print("\033[2J\033[H", end="")
            if ui == "panel":
                print(panel(raw, path, 220))
            else:
                for line in lines_for(raw, path):
                    print(line)
            print(f"\n[refresh {interval:.1f}s | q/Ctrl+C quit]")
            time.sleep(interval)
    except (KeyboardInterrupt, BrokenPipeError):
        return 0


def run_curses(path: str, interval: float, ui: str) -> int:
    def main(stdscr: Any) -> int:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.nodelay(True)
        stdscr.timeout(max(100, int(interval * 1000)))
        scroll = 0
        while True:
            raw = read_json(path)
            max_y, max_x = stdscr.getmaxyx()
            stdscr.erase()
            rows = [panel(raw, path, max_x)] if ui == "panel" else lines_for(raw, path)
            visible = max(1, max_y - 1)
            max_scroll = max(0, len(rows) - visible)
            scroll = min(max(scroll, 0), max_scroll)
            for y, line in enumerate(rows[scroll:scroll+visible]):
                try:
                    stdscr.addnstr(y, 0, line, max(0, max_x-1))
                except curses.error:
                    pass
            footer = " q:quit  ↑/↓:scroll  PgUp/PgDn  Home/End  r:refresh"
            try:
                stdscr.addnstr(max_y-1, 0, footer, max(0, max_x-1), curses.A_REVERSE)
            except curses.error:
                pass
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (ord('q'), ord('Q')):
                return 0
            if ch in (ord('r'), ord('R')):
                continue
            if ch in (curses.KEY_DOWN, ord('j')):
                scroll += 1
            elif ch in (curses.KEY_UP, ord('k')):
                scroll -= 1
            elif ch == curses.KEY_NPAGE:
                scroll += max(1, visible-1)
            elif ch == curses.KEY_PPAGE:
                scroll -= max(1, visible-1)
            elif ch == curses.KEY_HOME:
                scroll = 0
            elif ch == curses.KEY_END:
                scroll = max_scroll
    return curses.wrapper(main)


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only JARVIS live LLM provider monitor")
    ap.add_argument("--state", default=None)
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    ap.add_argument("--ui", choices=("dashboard", "panel"), default="dashboard")
    ap.add_argument("--plain", action="store_true")
    args = ap.parse_args()
    path = resolve_state_path(args.state)
    interval = max(0.1, args.interval)
    if args.plain or not sys.stdout.isatty():
        return run_plain(path, interval, args.ui)
    try:
        return run_curses(path, interval, args.ui)
    except Exception as exc:
        print(f"[llm_monitor] curses failed: {exc}; falling back to plain")
        return run_plain(path, interval, args.ui)


if __name__ == "__main__":
    raise SystemExit(main())
