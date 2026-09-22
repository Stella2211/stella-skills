"""Behavioral tests for the packaged skill-use CLI and hook commands."""
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
NAMES = ("docs-writer", "long-task-execution")


class SkillUsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="stella hooks ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = os.environ.copy()
        self.env.pop("STELLA_SKILL_USAGE_DIR", None)
        self.env.pop("PLUGIN_DATA", None)
        self.env.update({
            "CODEX_HOME": str(self.root / "codex home"),
            "CODEX_THREAD_ID": "parent-123",
            "UV_PYTHON": sys.executable,
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_CACHE_DIR": str(self.root / "uv cache"),
        })
        self.plugins = {}
        for name in NAMES:
            target = self.root / "isolated plugins 日本語" / name
            shutil.copytree(REPO / "plugins" / name, target)
            self.plugins[name] = target

    def helper(self, name="docs-writer"):
        return self.plugins[name] / "hooks" / "skill-usage.py"

    def skill(self, name="docs-writer"):
        return self.plugins[name] / "skills" / name / "SKILL.md"

    def marker(self, name="docs-writer", thread="parent-123"):
        root = Path(self.env.get("STELLA_SKILL_USAGE_DIR") or
                    Path(self.env["CODEX_HOME"]) / "stella-skills" / "skill-usage")
        return root / thread / f"{name}.active"

    def cli(self, action, name="docs-writer", env=None, data=None):
        result = subprocess.run(
            [sys.executable, str(self.helper(name)), action],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=self.root, env=self.env if env is None else env, timeout=15,
        )
        return result

    def hook(self, name="docs-writer", source="compact", **extra):
        event = {"hook_event_name": "SessionStart", "source": source,
                 "session_id": "parent-123"}
        event.update(extra)
        return self.cli("hook", name, data=json.dumps(event).encode())

    def assert_silent(self, result, *, diagnostic=False):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"")
        if diagnostic:
            self.assertTrue(result.stderr)
        else:
            self.assertEqual(result.stderr, b"")

    def test_packaged_manifest_and_hook_matchers(self):
        for name in NAMES:
            with self.subTest(plugin=name):
                root = self.plugins[name]
                manifest = json.loads((root / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["hooks"], "./hooks/hooks.json")
                config = json.loads((root / manifest["hooks"]).read_text(encoding="utf-8"))
                self.assertEqual(set(config["hooks"]), {"SessionStart"})
                entry = config["hooks"]["SessionStart"][0]
                for source in ("compact", "clear"):
                    self.assertIsNotNone(re.fullmatch(entry["matcher"], source))
                for source in ("startup", "resume"):
                    self.assertIsNone(re.fullmatch(entry["matcher"], source))
                self.assertEqual(entry["hooks"][0]["additionalContextLimit"], 0)
                self.assertLessEqual(self.skill(name).stat().st_size, 16 * 1024)

    def test_unregistered_does_not_read_skill_or_create_state(self):
        for name in NAMES:
            self.skill(name).unlink()
            self.assert_silent(self.hook(name))
        self.assertFalse(Path(self.env["CODEX_HOME"]).exists())

    def test_activate_is_idempotent_and_restore_is_repeatable(self):
        for name in NAMES:
            with self.subTest(plugin=name):
                result = self.cli("activate", name)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(json.loads(result.stdout)["active"])
                marker = self.marker(name)
                self.assertEqual(marker.read_bytes(), b"")
                before = marker.stat().st_mtime_ns
                self.assertEqual(self.cli("activate", name).returncode, 0)
                self.assertEqual(marker.stat().st_mtime_ns, before)
                for _ in range(2):
                    result = self.hook(name)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    context = json.loads(result.stdout)["hookSpecificOutput"]
                    self.assertEqual(context["hookEventName"], "SessionStart")
                    # The hook preserves installed text, including Windows CRLF.
                    expected = self.skill(name).read_bytes().decode("utf-8-sig").rstrip()
                    self.assertIn(expected, context["additionalContext"])
                    # Windows temp paths may use an 8.3 alias such as RUNNER~1.
                    self.assertIn(str(self.skill(name).resolve()), context["additionalContext"])

    def test_plugins_do_not_activate_each_other(self):
        self.cli("activate", "long-task-execution")
        self.assert_silent(self.hook("docs-writer"))
        self.assertTrue(self.hook("long-task-execution").stdout)

    def test_child_registration_does_not_reach_parent(self):
        child = {**self.env, "CODEX_THREAD_ID": "child-456"}
        self.assertEqual(self.cli("activate", env=child).returncode, 0)
        self.assertTrue(self.marker(thread="child-456").exists())
        self.assert_silent(self.hook())
        self.cli("activate")
        self.assert_silent(self.hook(agent_id="child-456"))
        self.assert_silent(self.hook(session_id="another-thread"))

    def test_hook_uses_event_session_not_native_shell_id(self):
        self.cli("activate")
        self.env["CODEX_THREAD_ID"] = "different-shell-thread"
        self.assertTrue(self.hook().stdout)

    def test_deactivate_is_idempotent(self):
        self.cli("activate")
        for _ in range(2):
            result = self.cli("deactivate")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)["active"])
        self.assert_silent(self.hook())

    def test_status_is_read_only(self):
        result = self.cli("status")
        self.assertFalse(json.loads(result.stdout)["active"])
        self.assertFalse(Path(self.env["CODEX_HOME"]).exists())

    def test_clear_only_removes_own_plugin_and_session(self):
        for name in NAMES:
            self.cli("activate", name)
        self.cli("activate", env={**self.env, "CODEX_THREAD_ID": "child-456"})
        self.assert_silent(self.hook(source="clear"))
        self.assertFalse(self.marker().exists())
        self.assertTrue(self.marker("long-task-execution").exists())
        self.assertTrue(self.marker(thread="child-456").exists())
        self.assert_silent(self.hook(source="clear"))

    def test_other_lifecycle_events_preserve_registration(self):
        self.cli("activate")
        for source in ("startup", "resume"):
            self.assert_silent(self.hook(source=source))
        for event in ("PostCompact", "SessionEnd"):
            self.assert_silent(self.hook(hook_event_name=event))
        self.assertTrue(self.marker().exists())

    def test_invalid_thread_ids_do_not_write_state(self):
        for thread in (None, "", "../other", "a/b", "a\\b", ".", "x" * 129):
            env = self.env.copy()
            if thread is None:
                env.pop("CODEX_THREAD_ID")
            else:
                env["CODEX_THREAD_ID"] = thread
            result = self.cli("activate", env=env)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
        self.assertFalse(Path(self.env["CODEX_HOME"]).exists())

    def test_malformed_events_are_nonblocking_and_silent(self):
        for data in (b"invalid", b"[]", b"x" * (64 * 1024 + 1)):
            self.assert_silent(self.cli("hook", data=data), diagnostic=True)
        self.assert_silent(self.hook(session_id="../bad"), diagnostic=True)

    def test_bad_skill_never_causes_fallback_injection(self):
        self.cli("activate")
        for data in (b"x" * (16 * 1024 + 1), b"\xff", b""):
            self.skill().write_bytes(data)
            self.assert_silent(self.hook(), diagnostic=True)
        self.skill().unlink()
        self.assert_silent(self.hook(), diagnostic=True)

    def test_marker_directory_is_an_error_not_activation(self):
        self.marker().mkdir(parents=True)
        self.assert_silent(self.hook(), diagnostic=True)
        self.assertEqual(self.cli("activate").returncode, 1)

    def test_shared_override_and_plugin_move_preserve_registration(self):
        self.env["STELLA_SKILL_USAGE_DIR"] = str(self.root / "shared state")
        self.cli("activate")
        previous = self.plugins["docs-writer"]
        moved = self.root / "new installed version" / "docs-writer"
        moved.parent.mkdir()
        shutil.move(str(previous), moved)
        self.plugins["docs-writer"] = moved
        self.assertTrue(self.hook().stdout)
        self.assertFalse(Path(self.env["CODEX_HOME"]).exists())

    def test_relative_override_is_rejected(self):
        self.env["STELLA_SKILL_USAGE_DIR"] = "relative"
        self.assertEqual(self.cli("activate").returncode, 1)
        self.assert_silent(self.hook(), diagnostic=True)
        self.assertFalse((self.root / "relative").exists())

    @unittest.skipUnless(shutil.which("uv"), "uv unavailable: packaged shell command not exercised")
    def test_actual_packaged_hook_command(self):
        for name in NAMES:
            root = self.plugins[name]
            config = json.loads((root / "hooks/hooks.json").read_text(encoding="utf-8"))
            handler = config["hooks"]["SessionStart"][0]["hooks"][0]
            command = handler["commandWindows" if os.name == "nt" else "command"]
            env = {**self.env, "PLUGIN_ROOT": str(root)}
            event = json.dumps({"hook_event_name": "SessionStart", "source": "compact", "session_id": "parent-123"}).encode()
            for active in (False, True):
                if active:
                    self.cli("activate", name)
                result = subprocess.run(command, shell=True, input=event,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        cwd=self.root, env=env, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                if active:
                    self.assertIn(name, json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])
                else:
                    self.assertEqual(result.stdout, b"")
            if os.name == "nt" and shutil.which("pwsh"):
                result = subprocess.run(["pwsh", "-NoProfile", "-NonInteractive", "-Command", command],
                                        input=event, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        cwd=self.root, env=env, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(name, json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":
    unittest.main()
