"""Behavior tests for each independently installable skill-usage hook."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
PLUGINS = ("docs-writer", "long-task-execution")


class SkillUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="stella hooks ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.install = self.root / "installed 日本語"
        self.env = os.environ.copy()
        for key in ("CODEX_HOME", "CODEX_THREAD_ID", "STELLA_SKILL_USAGE_DIR", "PLUGIN_ROOT", "PLUGIN_DATA"):
            self.env.pop(key, None)
        self.env["CODEX_HOME"] = str(self.root / "codex home")
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        for name in PLUGINS:
            destination = self.install / name
            for relative in ("hooks/skill-usage.py", "hooks/hooks.json", ".codex-plugin/plugin.json", f"skills/{name}/SKILL.md"):
                output = destination / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO / "plugins" / name / relative, output)

    def invoke(self, name, action, thread="parent-1", event=None, raw=None, extra_env=None):
        env = dict(self.env)
        if thread is not None:
            env["CODEX_THREAD_ID"] = thread
        env.update(extra_env or {})
        data = raw if raw is not None else json.dumps(event or {}).encode()
        return subprocess.run(
            [sys.executable, str(self.install / name / "hooks/skill-usage.py"), action],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=self.root, env=env, timeout=15,
        )

    def compact(self, name, session="parent-1", **kwargs):
        return self.invoke(name, "hook", event={"hook_event_name": "SessionStart", "source": "compact", "session_id": session}, **kwargs)

    def marker(self, name, thread="parent-1"):
        return Path(self.env["CODEX_HOME"]) / "stella-skills/skill-usage" / thread / f"{name}.active"

    def assert_silent(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")

    def test_unused_skills_are_silent_without_state_or_skill_read(self):
        for name in PLUGINS:
            (self.install / name / "skills" / name / "SKILL.md").unlink()
            result = self.compact(name)
            self.assert_silent(result)
            self.assertEqual(result.stderr, b"")
        self.assertFalse(Path(self.env["CODEX_HOME"]).exists())

    def test_activation_is_idempotent_and_restores_exact_skill(self):
        for name in PLUGINS:
            for _ in range(2):
                result = self.invoke(name, "activate")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(result.stdout)["active"])
            self.assertEqual(self.marker(name).read_bytes(), b"")
            result = self.compact(name)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)["hookSpecificOutput"]
            self.assertEqual(output["hookEventName"], "SessionStart")
            body = (self.install / name / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(body.rstrip(), output["additionalContext"])
            self.assertLessEqual(len(output["additionalContext"].encode()), 20 * 1024)

    def test_threads_and_plugins_do_not_share_activation(self):
        self.invoke("docs-writer", "activate", thread="child-1")
        self.assert_silent(self.compact("docs-writer"))
        self.invoke("long-task-execution", "activate")
        self.assert_silent(self.compact("docs-writer"))
        self.assert_silent(self.compact("long-task-execution", session="unrelated-1"))
        self.assertTrue(self.compact("long-task-execution").stdout)

    def test_deactivation_does_not_affect_other_plugin(self):
        for name in PLUGINS:
            self.invoke(name, "activate")
        for _ in range(2):
            result = self.invoke("docs-writer", "deactivate")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_silent(self.compact("docs-writer"))
        self.assertTrue(self.compact("long-task-execution").stdout)

    def test_clear_removes_only_matching_plugin_and_thread(self):
        for name in PLUGINS:
            for thread in ("parent-1", "child-1"):
                self.invoke(name, "activate", thread=thread)
        result = self.invoke("docs-writer", "hook", event={"hook_event_name": "SessionStart", "source": "clear", "session_id": "parent-1"})
        self.assert_silent(result)
        self.assertFalse(self.marker("docs-writer").exists())
        self.assertTrue(self.marker("docs-writer", "child-1").exists())
        self.assertTrue(self.marker("long-task-execution").exists())

    def test_resume_shutdown_and_other_events_preserve_state(self):
        self.invoke("docs-writer", "activate")
        for event in (
            {"hook_event_name": "SessionStart", "source": "resume", "session_id": "parent-1"},
            {"hook_event_name": "SessionStart", "source": "startup", "session_id": "parent-1"},
            {"hook_event_name": "SessionEnd", "session_id": "parent-1"},
            {"hook_event_name": "PostCompact", "session_id": "parent-1"},
            {"hook_event_name": "SessionStart", "source": "compact", "session_id": "parent-1", "agent_id": "child-1"},
        ):
            self.assert_silent(self.invoke("docs-writer", "hook", event=event))
            self.assertTrue(self.marker("docs-writer").exists())

    def test_missing_or_invalid_registration_id_never_falls_back(self):
        for thread in (None, "", "../parent-1", "/tmp/parent", "parent/child"):
            result = self.invoke("docs-writer", "activate", thread=thread)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
        self.assertFalse(Path(self.env["CODEX_HOME"]).exists())

    def test_invalid_event_is_nonblocking_and_does_not_inject(self):
        self.invoke("docs-writer", "activate")
        for raw in (b"not json", b"[]", b"x" * (64 * 1024 + 1)):
            self.assert_silent(self.invoke("docs-writer", "hook", raw=raw))
        for session in ("", "../parent-1", None):
            self.assert_silent(self.compact("docs-writer", session=session))

    def test_bad_registered_skill_never_emits_partial_content(self):
        self.invoke("docs-writer", "activate")
        path = self.install / "docs-writer/skills/docs-writer/SKILL.md"
        for data in (b"x" * (16 * 1024 + 1), b"\xff", b"", b" \n"):
            path.write_bytes(data)
            result = self.compact("docs-writer")
            self.assert_silent(result)
            self.assertTrue(result.stderr)
        path.unlink()
        self.assert_silent(self.compact("docs-writer"))

    def test_explicit_state_path_is_shared_with_hooks(self):
        env = {"STELLA_SKILL_USAGE_DIR": str(self.root / "shared markers"), "PLUGIN_DATA": str(self.root / "hook only data")}
        self.assertEqual(self.invoke("docs-writer", "activate", extra_env=env).returncode, 0)
        self.assertTrue(self.compact("docs-writer", extra_env=env).stdout)
        self.assertFalse(Path(env["PLUGIN_DATA"]).exists())
        self.assert_silent(self.compact("docs-writer"))
        self.assertNotEqual(self.invoke("docs-writer", "activate", extra_env={"STELLA_SKILL_USAGE_DIR": "relative"}).returncode, 0)

    def test_state_error_is_nonblocking_for_hook(self):
        broken = self.root / "not a directory"
        broken.write_text("blocked", encoding="utf-8")
        env = {"STELLA_SKILL_USAGE_DIR": str(broken / "state")}
        self.assertNotEqual(self.invoke("docs-writer", "activate", extra_env=env).returncode, 0)
        self.assert_silent(self.compact("docs-writer", extra_env=env))

    def test_plugin_move_and_update_keeps_registration(self):
        self.invoke("docs-writer", "activate")
        moved = self.root / "new plugin version"
        self.install.rename(moved)
        self.install = moved
        path = moved / "docs-writer/skills/docs-writer/SKILL.md"
        path.write_text("# Updated installed skill\n", encoding="utf-8")
        self.assertIn("Updated installed skill", json.loads(self.compact("docs-writer").stdout)["hookSpecificOutput"]["additionalContext"])

    def test_status_does_not_create_state(self):
        output = self.invoke("docs-writer", "status")
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertFalse(json.loads(output.stdout)["active"])
        self.assertFalse(Path(self.env["CODEX_HOME"]).exists())

    def test_packaging_and_bundled_command(self):
        # With uv available (CI), execute the actual universal hook command.
        for name in PLUGINS:
            root = self.install / name
            manifest = json.loads((root / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["hooks"], "./hooks/hooks.json")
            settings = json.loads((root / "hooks/hooks.json").read_text(encoding="utf-8"))
            self.assertEqual(set(settings["hooks"]), {"SessionStart"})
            config = settings["hooks"]["SessionStart"][0]
            self.assertTrue(re.fullmatch(config["matcher"], "compact"))
            self.assertTrue(re.fullmatch(config["matcher"], "clear"))
            self.assertIsNone(re.fullmatch(config["matcher"], "resume"))
            handler = config["hooks"][0]
            self.assertEqual(handler["additionalContextLimit"], 0)
            if not shutil.which("uv"):
                continue
            self.invoke(name, "activate")
            env = dict(self.env, PLUGIN_ROOT=str(root), UV_PYTHON=sys.executable)
            data = json.dumps({"hook_event_name": "SessionStart", "source": "compact", "session_id": "parent-1"}).encode()
            commands = [["sh", "-c", handler["command"]]] if os.name != "nt" else [["cmd", "/d", "/s", "/c", handler["command"]], ["powershell", "-NoProfile", "-Command", handler["command"]]]
            for command in commands:
                result = subprocess.run(command, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=self.root, env=env, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"], "SessionStart")


if __name__ == "__main__":
    unittest.main()
