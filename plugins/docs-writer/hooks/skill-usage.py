#!/usr/bin/env python3
"""Record explicit per-thread skill use and restore it after root compaction.

Standalone in each plugin: no transcript parsing, network, third-party package,
or imports from a sibling plugin. The marker deliberately contains no paths.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

MAX_EVENT_BYTES = 64 * 1024
MAX_SKILL_BYTES = 16 * 1024
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


def identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Missing or invalid {label}; do not substitute another thread's ID")
    return value


def plugin_info() -> tuple[str, Path]:
    # Resolve from this file, not cwd, a version directory name, or another plugin.
    root = Path(__file__).resolve().parent.parent
    manifest = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    name = identifier(manifest["name"], "plugin name")
    return name, root / "skills" / name / "SKILL.md"


def state_root() -> Path:
    # Use the SAME location for native-shell registration and plugin hooks.
    # PLUGIN_DATA is hook-only and therefore is deliberately not a fallback.
    override = os.environ.get("STELLA_SKILL_USAGE_DIR")
    if override:
        root = Path(override).expanduser()
    else:
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
        root = home / "stella-skills" / "skill-usage"
    if not root.is_absolute():
        raise ValueError("CODEX_HOME / STELLA_SKILL_USAGE_DIR must resolve to an absolute path")
    return root


def marker_path(name: str, thread_id: str) -> Path:
    return state_root() / thread_id / f"{name}.active"


def registered(marker: Path) -> bool:
    if marker.is_symlink():
        raise ValueError("A usage marker must not be a symbolic link")
    if marker.exists() and not marker.is_file():
        raise ValueError("A usage marker must be a regular file")
    return marker.is_file()


def read_event() -> dict:
    data = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
    if len(data) > MAX_EVENT_BYTES:
        raise ValueError("Hook input exceeds 64 KiB")
    event = json.loads(data)
    if not isinstance(event, dict):
        raise ValueError("Hook input must be a JSON object")
    return event


def run_hook() -> None:
    event = read_event()
    if event.get("hook_event_name") != "SessionStart":
        return
    if event.get("source") not in ("compact", "clear"):
        return
    # This integration is root-only. Never use a child's shared session_id.
    if event.get("agent_id"):
        return
    thread_id = identifier(event.get("session_id"), "hook session_id")
    name, skill_path = plugin_info()
    marker = marker_path(name, thread_id)
    if event["source"] == "clear":
        # Remove only this plugin's marker; other plugins clear their own.
        if registered(marker):
            marker.unlink(missing_ok=True)
        return
    if not registered(marker):
        # No state creation, SKILL read, reminder, or fallback injection.
        return
    with skill_path.open("rb") as handle:
        data = handle.read(MAX_SKILL_BYTES + 1)
    if len(data) > MAX_SKILL_BYTES:
        raise ValueError(f"{name}: SKILL.md exceeds 16 KiB; read it manually")
    # Git may check out CRLF on Windows. Send platform-independent text.
    text = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise ValueError(f"{name}: SKILL.md is empty")
    context = (
        f"[stella-skills: restored {name} after compaction]\n"
        "This skill was explicitly adopted in this thread. Apply it only where\n"
        "relevant to the ongoing request; restoration does not start new work\n"
        "or expand authorization. Do not register it again or reread identical\n"
        "text. Resolve references relative to the SKILL.md path below.\n"
        f"SKILL.md: {skill_path}\n\n{text.rstrip()}\n"
        f"[end restored skill: {name}]"
    )
    # Bound path/header overhead as well as the skill body.
    if len(context.encode("utf-8")) > 20 * 1024:
        raise ValueError("Restored context exceeds 20 KiB")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart", "additionalContext": context
    }}, ensure_ascii=True))


def run_command(action: str) -> None:
    # Native execution supplies the executing agent's thread, not its parent's.
    thread_id = identifier(os.environ.get("CODEX_THREAD_ID"), "CODEX_THREAD_ID")
    name, _ = plugin_info()
    marker = marker_path(name, thread_id)
    active = registered(marker)
    if action == "activate" and not active:
        marker.parent.mkdir(parents=True, exist_ok=True)
        try:
            with marker.open("x", encoding="utf-8"):
                pass
        except FileExistsError:
            # Concurrent registration of the same empty marker is harmless.
            if not registered(marker):
                raise
    elif action == "deactivate" and active:
        marker.unlink(missing_ok=True)
    print(json.dumps({
        "skill": name, "thread_id": thread_id,
        "active": registered(marker), "marker": str(marker)
    }, ensure_ascii=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("activate", "deactivate", "status", "hook"))
    args = parser.parse_args()
    try:
        if args.action == "hook":
            run_hook()
        else:
            run_command(args.action)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"stella-skills usage: {exc}", file=sys.stderr)
        # A restoration failure must not stop the user's task or inject all skills.
        return 0 if args.action == "hook" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
