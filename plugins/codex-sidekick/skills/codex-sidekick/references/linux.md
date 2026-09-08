# Linux: one-shot codex queue

Use a transient **user service** with `systemd-run --user`; use `--on-active=5m` for a five-minute delay. This is a detached service, not a `--scope`: the command continues after the launching shell exits, subject to the user's systemd session and service manager.

## Schedule

Replace every `<PLACEHOLDER>` with an actual value. Use an absolute executable path and pass the same explicit `CODEX_HOME` that the interactive Codex installation uses. Keep the unit name unique and stable so status/cancel commands can address it.

```sh
CODEX_HOME_VALUE="<CODEX_HOME_ABSOLUTE_PATH>"
CODEX_EXE="<CODEX_ABSOLUTE_EXECUTABLE>"
UNIT="codex-queue-<UNIQUE_SUFFIX>"

systemd-run --user --unit="$UNIT" --on-active=5m --timer-property=AccuracySec=1s \
  --setenv=CODEX_HOME="$CODEX_HOME_VALUE" \
  --working-directory="<ABSOLUTE_WORKSPACE>" -- "$CODEX_EXE" queue \
  --thread "<THREAD_ID>" --message 'Notification test: reply with the current time.'
```

`--on-active=5m` starts five minutes after the timer is activated; `--timer-property=AccuracySec=1s` requests one-second timer accuracy. Verify the executable and arguments with `command -v`/`readlink -f` before scheduling. Quote each value; if a wrapper is needed, make it an executable script with a shebang and have it `exec` Codex so its exit status propagates. Do not embed secrets or untrusted text in a shell command.

The receiving app-server must be live with the target loaded. Queue the message even if the target is busy: idle dispatch can run after the current turn. Timer completion does not establish message consumption or an OS push notification.

## Inspect, cancel, and clean up

```sh
systemctl --user status "$UNIT.timer" "$UNIT.service" --no-pager
systemctl --user show "$UNIT.timer" "$UNIT.service" -p Id,ActiveState,SubState,Result,ExecMainStatus,ExecMainExitTimestamp
journalctl --user -u "$UNIT" --no-pager

systemctl --user stop "$UNIT.timer" "$UNIT.service"
systemctl --user reset-failed "$UNIT"
```

Stopping the timer cancels a pending run; stopping the service terminates an active run. Use `systemctl --user reset-failed` for retained failure state. Collect status and journal evidence before cleanup; transient unit state may be unloaded after completion. If a unit has already been unloaded, confirm that specific unit is absent and report it as already removed. Only reset retained failed state when present. Keep permission, manager-access, and other unexpected errors visible; do not report cancellation success without checking the result.

## Limits

- This is a best-effort delay, not a durable calendar or queue. User service availability, lingering/logouts, suspend, sleep, shutdown, and reboot can delay or prevent execution. Confirm the host's user-manager/linger policy before relying on it.
- `CODEX_HOME` is set explicitly for the service; do not assume the interactive shell environment is inherited.
- Use the same interactive user and permissions. A user service does not become a system service or gain privileges.
- No OS-level watcher is installed: report queue acceptance or failure from `systemctl` and `journalctl`.

Official references: [systemd-run](https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html), [systemd.timer](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html), [systemctl](https://www.freedesktop.org/software/systemd/man/latest/systemctl.html), and [journalctl](https://www.freedesktop.org/software/systemd/man/latest/journalctl.html).

The sample is a relative awake-time delay: the monotonic clock pauses during suspend. Use an explicit `--on-calendar` deadline for wall-clock semantics across sleep. This transient recipe does not survive reboot; durable scheduling needs installed timer/service files. Do not enable lingering automatically. If systemd user services are unavailable, inspect the host scheduler (for example an already-configured atd) rather than silently falling back to nohup. These Linux instructions are documentation-based, not tested on this macOS host.
