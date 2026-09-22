"""Exercise packaged helpers as processes; Codex lifecycle integration is separate."""
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
        self.temp = tempfile.TemporaryDirectory(prefix="stella hooks ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.installs = {}
        for name in PLUGINS:
            target = self.root / "plugin cache 日本語" / name / "0.1.1"
            for rel in (".codex-plugin/plugin.json", "hooks/skill-usage.py",
                        "hooks/hooks.json", f"skills/{name}/SKILL.md"):
                dst = target / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(REPO / "plugins" / name / rel, dst)
            self.installs[name] = target
        self.env = os.environ.copy()
        self.env.pop("STELLA_SKILL_USAGE_DIR", None)
        self.env.pop("PLUGIN_DATA", None)
        self.env.update(CODEX_HOME=str(self.root / "codex"),
                        CODEX_THREAD_ID="parent-001", PYTHONUTF8="1",
                        UV_PYTHON=sys.executable, UV_CACHE_DIR=str(self.root / "uv-cache"))

    def invoke(self, action, name="docs-writer", event=None, env=None, raw=None):
        return subprocess.run(
            [sys.executable, str(self.installs[name] / "hooks/skill-usage.py"), action],
            input=raw if raw is not None else (json.dumps(event) if event is not None else ""),
            text=True, encoding="utf-8", capture_output=True, env=env or self.env,
            cwd=self.root, timeout=10,
        )

    def hook(self, name="docs-writer", source="compact", thread="parent-001", **extra):
        event = dict(hook_event_name="SessionStart", source=source, session_id=thread)
        event.update(extra)
        return self.invoke("hook", name, event=event)

    def marker(self, name="docs-writer", thread="parent-001"):
        return self.root / "codex/stella-skills/skill-usage" / thread / f"{name}.active"

    def assert_silent(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_unused_is_silent_without_reading_skill_or_creating_state(self):
        for name in PLUGINS:
            with self.subTest(name=name):
                (self.installs[name] / f"skills/{name}/SKILL.md").unlink()
                self.assert_silent(self.hook(name))
        self.assertFalse((self.root / "codex").exists())

    def test_activation_is_idempotent_and_restores_exact_text(self):
        for name in PLUGINS:
            with self.subTest(name=name):
                first = self.invoke("activate", name)
                self.assertEqual(first.returncode, 0, first.stderr)
                self.assertTrue(json.loads(first.stdout)["active"])
                self.assertEqual(self.marker(name).stat().st_size, 0)
                old_time = self.marker(name).stat().st_mtime_ns
                self.assertEqual(self.invoke("activate", name).returncode, 0)
                self.assertEqual(self.marker(name).stat().st_mtime_ns, old_time)
                result = self.hook(name)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = json.loads(result.stdout)["hookSpecificOutput"]
                self.assertEqual(output["hookEventName"], "SessionStart")
                text = (self.installs[name] / f"skills/{name}/SKILL.md").read_text(encoding="utf-8")
                self.assertIn(text.rstrip(), output["additionalContext"])
                self.assertLessEqual(len(output["additionalContext"].encode()), 20 * 1024)

    def test_plugins_and_threads_are_isolated(self):
        self.assertEqual(self.invoke("activate").returncode, 0)
        self.assert_silent(self.hook("long-task-execution"))
        self.assert_silent(self.hook(thread="other-002"))
        child_env = dict(self.env, CODEX_THREAD_ID="child-003")
        self.assertEqual(self.invoke("activate", "long-task-execution", env=child_env).returncode, 0)
        self.assertTrue(self.marker("long-task-execution", "child-003").exists())
        self.assertFalse(self.marker("long-task-execution").exists())
        self.assert_silent(self.hook("long-task-execution"))

    def test_hook_uses_event_id_not_shell_thread_id(self):
        self.invoke("activate")
        env = dict(self.env, CODEX_THREAD_ID="unrelated-child")
        result = self.invoke("hook", event={"hook_event_name": "SessionStart", "source": "compact",
                                            "session_id": "parent-001"}, env=env)
        self.assertIn("additionalContext", result.stdout)

    def test_child_hook_does_not_restore_or_clear_parent(self):
        self.invoke("activate")
        self.assert_silent(self.hook(agent_id="child-003"))
        self.assert_silent(self.hook(source="clear", agent_id="child-003"))
        self.assertTrue(self.marker().exists())

    def test_deactivate_and_status(self):
        self.assertFalse(json.loads(self.invoke("status").stdout)["active"])
        self.invoke("activate")
        self.assertTrue(json.loads(self.invoke("status").stdout)["active"])
        for _ in range(2):
            result = self.invoke("deactivate")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(json.loads(result.stdout)["active"])
        self.assert_silent(self.hook())

    def test_clear_only_removes_current_plugins_marker(self):
        for name in PLUGINS:
            self.invoke("activate", name)
        self.assert_silent(self.hook(source="clear"))
        self.assertFalse(self.marker().exists())
        self.assertTrue(self.marker("long-task-execution").exists())
        self.assert_silent(self.hook("long-task-execution", source="clear"))
        self.assert_silent(self.hook(source="clear"))

    def test_resume_startup_and_session_end_do_not_erase_or_inject(self):
        self.invoke("activate")
        for source in ("resume", "startup"):
            self.assert_silent(self.hook(source=source))
        self.assert_silent(self.invoke("hook", event={"hook_event_name": "SessionEnd", "session_id": "parent-001"}))
        self.assertTrue(self.marker().exists())

    def test_missing_and_invalid_native_ids_fail_without_writes(self):
        for value in (None, "", "../parent", "/absolute", "bad\\id", "x" * 129):
            with self.subTest(value=value):
                env = dict(self.env)
                if value is None:
                    env.pop("CODEX_THREAD_ID", None)
                else:
                    env["CODEX_THREAD_ID"] = value
                result = self.invoke("activate", env=env)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
        self.assertFalse((self.root / "codex").exists())

    def test_invalid_events_never_inject_or_block(self):
        for raw in ("{bad", "[]", "x" * (64 * 1024 + 1),
                    '{"hook_event_name":"SessionStart","source":"compact"}',
                    '{"hook_event_name":"SessionStart","source":"compact","session_id":"../bad"}'):
            with self.subTest(length=len(raw)):
                result = self.invoke("hook", raw=raw)
                self.assert_silent(result)
                self.assertTrue(result.stderr)

    def test_bad_skill_does_not_fall_back_to_other_skills(self):
        self.invoke("activate")
        path = self.installs["docs-writer"] / "skills/docs-writer/SKILL.md"
        for content in (b"x" * (16 * 1024 + 1), b"\xff", b""):
            path.write_bytes(content)
            result = self.hook()
            self.assert_silent(result)
            self.assertTrue(result.stderr)
        path.unlink()
        self.assert_silent(self.hook())

    def test_custom_state_matches_shell_and_hook_ignores_plugin_data(self):
        env = dict(self.env, STELLA_SKILL_USAGE_DIR=str(self.root / "custom state"))
        result = self.invoke("activate", env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        event = {"hook_event_name": "SessionStart", "source": "compact", "session_id": "parent-001"}
        env["PLUGIN_DATA"] = str(self.root / "different hook-only path")
        result = self.invoke("hook", event=event, env=env)
        self.assertIn("additionalContext", result.stdout)
        self.assertFalse(Path(env["PLUGIN_DATA"]).exists())

    def test_storage_errors_are_reported_without_all_skill_fallback(self):
        blocker = self.root / "file-not-directory"
        blocker.write_text("existing", encoding="utf-8")
        env = dict(self.env, STELLA_SKILL_USAGE_DIR=str(blocker))
        self.assertNotEqual(self.invoke("activate", env=env).returncode, 0)
        result = self.invoke("hook", event={"hook_event_name": "SessionStart", "source": "compact",
                                            "session_id": "parent-001"}, env=env)
        self.assert_silent(result)
        self.assertEqual(blocker.read_text(encoding="utf-8"), "existing")

    def test_new_install_path_and_updated_skill_keep_registration(self):
        self.invoke("activate")
        old = self.installs["docs-writer"]
        new = old.parent / "0.1.2"
        old.rename(new)
        self.installs["docs-writer"] = new
        path = new / "skills/docs-writer/SKILL.md"
        path.write_text("# Updated skill\n日本語の知見\n", encoding="utf-8")
        result = self.hook()
        self.assertIn("日本語の知見", json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])

    def test_manifests_and_hook_config(self):
        for name in PLUGINS:
            root = self.installs[name]
            manifest = json.loads((root / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
            config = json.loads((root / manifest["hooks"]).read_text(encoding="utf-8"))
            self.assertEqual(set(config["hooks"]), {"SessionStart"})
            group = config["hooks"]["SessionStart"][0]
            self.assertIsNotNone(re.fullmatch(group["matcher"], "compact"))
            self.assertIsNotNone(re.fullmatch(group["matcher"], "clear"))
            self.assertIsNone(re.fullmatch(group["matcher"], "resume"))
            handler = group["hooks"][0]
            self.assertEqual(handler["type"], "command")
            self.assertEqual(handler["additionalContextLimit"], 0)
            self.assertIn("PLUGIN_ROOT", handler["command"])
            self.assertIn("PLUGIN_ROOT", handler["commandWindows"])
        self.assertEqual((self.installs[PLUGINS[0]] / "hooks/skill-usage.py").read_bytes(),
                         (self.installs[PLUGINS[1]] / "hooks/skill-usage.py").read_bytes())

    @unittest.skipUnless(shutil.which("uv"), "uv is needed to exercise the actual hook command")
    def test_packaged_hook_command_with_spaces_and_unicode(self):
        for name in PLUGINS:
            self.invoke("activate", name)
            root = self.installs[name]
            handler = json.loads((root / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]["SessionStart"][0]["hooks"][0]
            command = handler["commandWindows" if os.name == "nt" else "command"]
            env = dict(self.env, PLUGIN_ROOT=str(root))
            result = subprocess.run(command, shell=True, input=json.dumps({
                "hook_event_name": "SessionStart", "source": "compact", "session_id": "parent-001"}),
                text=True, encoding="utf-8", capture_output=True, env=env, cwd=self.root, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(name, json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":
    unittest.main()
