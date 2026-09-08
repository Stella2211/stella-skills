# macOS: one-time launchd job

Use a temporary plist loaded into `gui/<uid>`. It need not be installed in `~/Library/LaunchAgents`; manual bootstrap avoids creating a login-persistent installation. Keep its script/configuration and logs in a task-specific directory that survives the requested delay.

## Build the job

Resolve the actual `codex` executable and current thread first. Generate the plist with a serializer such as Python's `plistlib` (run Python via `uv run --no-project python` when that is the local convention). Do not concatenate arbitrary message text into XML or shell code.

Set these fields:

| Field | Value |
| --- | --- |
| `Label` | Unique label such as `local.codex.queue.<unique-suffix>` |
| `RunAtLoad` | `true` |
| `KeepAlive` | `false` |
| `WorkingDirectory` | Existing absolute workspace path |
| `EnvironmentVariables` | Explicit actual `CODEX_HOME` if customized, plus PATH needed by any executable wrapper |
| `StandardOutPath`, `StandardErrorPath` | Absolute paths in the task directory |

For a short delay, use this `ProgramArguments` array. Each row below is a separate argument, not a command to paste into a shell:

```text
/bin/sh
-c
/bin/sleep "$1" || exit; shift; exec "$@"
codex-queue-timer
REMAINING_SECONDS
/absolute/path/to/codex
queue
--thread
THREAD_ID
--message
THE_LITERAL_USER_AUTHORIZED_MESSAGE
```

The fixed shell body uses positional arguments so the message is not interpreted as shell source. `exec` preserves the Codex CLI exit status. This is a one-time relative wait; keep the Mac awake for a straightforward five-minute test. Compute the remaining seconds immediately before registration and record the requested due time separately.

For a wall-clock schedule across sleep, use `StartCalendarInterval` with month/day/hour/minute and invoke Codex directly. Omitted date fields are wildcards, there is no year field, and this is a repeating calendar rule: use an explicit completed marker and task-specific cleanup for one-time semantics. Calendar scheduling is minute-granularity. Do not combine it with `RunAtLoad` unless immediate execution is intended. A full restart requires a separate persistence design; a manually loaded temporary job is not a reboot-persistent scheduler.

## Register and verify

Replace the absolute plist path and label below with the generated values:

```sh
plutil -lint /absolute/task/job.plist
launchctl bootstrap "gui/$(id -u)" /absolute/task/job.plist
launchctl print "gui/$(id -u)/local.codex.queue.UNIQUE"
```

Use normal tool permission escalation if required. Inspect the specific job's action, state, run count, and last exit code. For a `RunAtLoad` wait, `running` is expected before the deadline. Read the log after the deadline for the queue acknowledgement. Do not treat bootstrap success as queue acceptance.

Cancel or unregister only this job:

```sh
launchctl bootout "gui/$(id -u)/local.codex.queue.UNIQUE"
```

Booting out a running job terminates it, so only clean up after it finishes, unless cancellation was requested. Retain logs for diagnosis. Do not issue `bootout` on an entire user domain.

## Why this choice

A launchd-owned job completed a ten-second log-write probe across tool returns in the observed macOS environment; a `nohup` child did not. The receiving Codex thread still needs to be live and loaded. Logging out ends the GUI-session context.

`launchctl submit` is shorter but its documented failure-restart behavior is a poor default for a one-shot message that might be duplicated. Use explicit `KeepAlive=false` instead. `StartInterval=300` is recurring, not a one-time five-minute delay.

Apple documents calendar jobs catching up on wake from sleep, but not missed power-off executions. See [Scheduling Timed Jobs](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html); confirm current details with local `man launchd.plist` and `man launchctl`.
