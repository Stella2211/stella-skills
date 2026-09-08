# Long-running jobs independent of Codex

Use this reference when the user wants a command or job to continue after the Codex app closes. This is a separate capability from delayed `codex queue` delivery. Do not launch a real process while documenting or planning the job.

## Define the lifecycle before setup

Clarify which interruption the job must survive:

- **App close:** the OS-owned job can continue if its executable, user session, working directory, and dependencies remain available.
- **Logout:** a per-user job may stop with the user session. Use the platform's user-service persistence only when requested and authorized; do not enable lingering automatically.
- **Sleep or suspend:** execution pauses unless the platform and power policy support wake-up. Do not promise progress during suspend.
- **Shutdown or reboot:** no running process survives a reboot. Transient systemd services and manually loaded temporary launchd jobs do not automatically restart afterward. Windows task definitions can persist, but restart requires a suitable trigger. Configure persistent registration and checkpoint-based recovery only when requested.

Treat a job as independent only when its executable, configuration, input, output directory, and dependencies are durable. Do not rely on temporary app services, a live tool session, shell state, or files in a temporary directory. Resolve absolute paths and the intended user/home explicitly.

## Platform patterns

### macOS: launchd

Create a task-specific plist and load it into the appropriate user domain. For a long-running command, use `RunAtLoad=true` and `KeepAlive=false`, and invoke the command directly in `ProgramArguments`. The command must run in the foreground; do not wrap it in `sleep`, append `&`, use `nohup`, or otherwise detach a child from launchd. Set an absolute `WorkingDirectory`, explicit environment, and durable `StandardOutPath` and `StandardErrorPath`. Inspect the job with `launchctl print` and stop only its label with `launchctl bootout`.

Read [macOS launchd reference](macos.md) for registration and cancellation details.

### Linux: systemd user service

For a long-running process, use a transient user service without a timer. `systemd-run --user --service-type=exec --remain-after-exit` keeps a useful completed unit for final status and exit evidence:

```sh
systemd-run --user --unit="codex-job-UNIQUE" \
  --service-type=exec --remain-after-exit \
  --working-directory="/absolute/workspace" -- \
  /absolute/path/to/command --arg value
```

Pass only the environment needed by the computation; `CODEX_HOME` is needed only for a Codex invocation. With `--remain-after-exit`, `active (exited)` means the command has finished, not that it is still computing: check `SubState`, `Result`, and `ExecMainStatus`. Use absolute paths and durable output locations. Inspect with `systemctl --user status/show` and `journalctl --user -u codex-job-UNIQUE`; stop only the named unit. This service still depends on the user manager and host lifecycle. Do not add `--on-active` or another timer when the user asked for an independently running job rather than delayed start.

Read [Linux systemd user reference](linux.md) for scheduler availability and lifecycle limits.

### Windows: Task Scheduler

Use a task action under the intended account, with an explicit working directory, durable logs, and settings appropriate to the requested lifecycle. For immediate execution, register the task without a time trigger and use `Start-ScheduledTask`; check its running state afterward. For a week-long job, explicitly choose an execution time limit that permits the requested duration; do not inherit an unexamined default that could terminate it early. Inspect the existing [Windows Task Scheduler reference](windows.md), especially task settings such as execution time limits, `StartWhenAvailable`, wake behavior, and battery restrictions. Do not silently change those settings or assume that a task survives logout, sleep, or reboot without checking its principal and trigger configuration.

## Progress reports through codex queue

Always include best-effort progress reporting to the intended Codex thread when setting up a long-running job. Use intermediate results when available, otherwise report observable job status without inventing progress. Reporting is part of the standard setup, but successful queue delivery is never a dependency of the computation. If delivery is unavailable, record progress and notification failures locally and continue the main process. Record the selected cadence and target when reporting job setup.

- Default to **once per hour**, with **roughly four hours as the longest regular reporting interval** when timed progress reporting is practical. The interval is for sending attempts, not a guarantee that Codex will consume the message on time.
- If timing cannot be predicted or timed reporting is unsuitable, choose meaningful milestones yourself, such as every **10% completed**, a completed phase, or a new validation result. Explain the choice; do not force an hourly mechanism into a job that cannot expose it. Use available status for a lightweight heartbeat when useful, clearly distinguishing it from new results.
- Send a new validation result when it requires assessment, even between periodic reports. Deduplicate by job ID and event/step ID and combine it with a due periodic report. Routine events can be coalesced; do not discard distinct validation measurements needed for consecutive-result decisions.
- Include the job ID, timestamp, progress (for example step/total), new metric values and their direction, checkpoint/result paths, and the requested assessment. Include enough context for a receiving turn to find the current job state without relying on conversation memory. Completion and failure can also trigger a final best-effort report.

### Keep reporting failures separate from computation

The main process must continue if Codex is closed, the CLI is missing, queue delivery fails, or delivery hangs. Prefer a separate OS-managed reporter that reads durable progress records, or a supervised asynchronous notification worker. Use bounded timeouts, caught errors, and bounded notification retries; the restriction on restarting failed computation below does not prohibit these notification retries; keep notification exit status separate from the computation's exit status. Do not put an unchecked `codex queue` under `set -e`, await an unbounded CLI call in a training step, or require a queue acknowledgement before proceeding.

Persist progress locally whether or not delivery works. Bound the notification backlog and coalesce stale routine updates; retain the full metric history separately. Track attempted delivery versus acknowledged queue IDs to reduce duplicates. When recovering, report current state and point to retained history rather than flooding the thread with old heartbeats. Stop the reporter after the job finishes and a bounded final delivery attempt; do not leave recurring notifications running forever.

### Validation-driven intervention

For a job such as 25,000 training steps with validation every 1,000 steps, save each validation result durably and use it as a review event in addition to the chosen reporting cadence. If the user requests early stopping, record the exact metric, minimize/maximize direction, threshold/comparison, and consecutive-result rule. Evaluate consecutive-result rules on distinct validation events, not repeated hourly reports of the same result, and persist the rule state across restarts. Do not assume that increasing validation accuracy is deterioration, or invent an unspecified threshold or patience count. Resolve missing stop criteria before enabling automatic intervention while proceeding with independent setup where possible.

A queue message can ask Codex to assess the results and request a checkpoint-aware graceful stop of this job. Before stopping, verify the current job identity and latest metric history so delayed or duplicate messages do not act on a stale run. If a deterministic user-authorized stop rule must work even while Codex is closed, enforce that rule in the training callback or an independent supervisor; use the queue for reporting and additional analysis. A notification failure alone must never trigger early stopping. Without a local rule, state that Codex-based intervention depends on Codex being available and may be delayed.

## Checkpoints and control

Long jobs need recoverable evidence, not only a final exit code. Before launch, assign a unique job ID and record the command, resolved paths, start time, and intended lifecycle. Write timestamped durable logs. For expensive restartable work, configure periodic checkpoints containing sufficient state to resume, such as phase/offset or model and optimizer state. Verify that the application supports recovery; a service restart alone cannot restore progress. Keep status inspectable through the platform manager and a job-owned status file or database.

Provide an explicit stop path that targets only the named job. Capture status and logs before cleanup. A stop, crash, logout, sleep, or reboot must leave enough evidence to determine whether work completed, paused, or failed. Do not automatically retry after failure or interruption unless the user authorized retries and the job is demonstrably resumable from its checkpoint; otherwise report the state for review.

A successful OS registration proves only that the platform accepted the job. Verify the process or unit is running, then verify checkpoints and final exit status. macOS scheduler registration, status, cleanup, and a short process continuing across tool returns were verified. The user also reported successful delayed-message and short long-job workflow tests. Controlled app-close lifecycle tests and a week-long continuous run have not been verified. Linux and Windows recipes are documentation-based. Do not broaden these claims without new evidence.
