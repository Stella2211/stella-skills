---
name: codex-sidekick
description: Unofficial personal helper to queue messages or schedule later Codex turns, and run long commands under launchd, systemd, or Task Scheduler so they survive chat or Codex app closure. Use for delayed reminders, missing queue messages, and independent training, rendering, or batch jobs.
---

# Codex Sidekick

This is a personal, unofficial skill, not an OpenAI-provided feature. It uses the installed Codex CLI and OS service managers.

Support two workflows: send a message to an existing Codex thread, or hand a long-running command to an OS service manager so its lifetime is independent of the chat and Codex app. A queued message can start agent work; it is not necessarily a desktop push notification.

## Choose the workflow

- **Immediate or delayed message:** follow the queue steps below and the relevant OS reference.
- **Long command that should survive app closure, with progress reports:** read [Independent long-running jobs](references/long-running.md). Launch the actual computation under the OS manager without a timer unless a delayed start is requested, and always include best-effort progress reporting to the intended Codex thread. Report hourly by default, roughly no more than four hours apart when practical, or at suitable milestones such as each 10% or validation result. Keep the computation and its saved results independent: queue failure, notification timeout, or a closed receiving app must never stop or block the main process. If delivery is unavailable, retain progress locally and continue the computation. For separately authorized unattended analysis, `codex exec` can be an external follow-up, but do not silently substitute it for a requested same-thread reply.

For long jobs, verify **registered / running / completed** using the manager's job ID, process status, logs, exit status, and output artifacts. Queue-specific verification below applies only to message delivery. Do not report a job complete when only submission succeeded. Store the command/configuration, working directory, logs, output path, and stop/status commands where they remain usable after this chat ends. OS ownership changes process lifetime, not authorization; honor normal sandbox and approval boundaries.

## Establish the queue target and intent

- Check `codex --version` and `codex queue --help`. If unavailable, report that limitation; do not silently substitute `codex exec` or create a new conversation.
- For “this thread”, obtain the current runtime's thread ID (for example `printenv CODEX_THREAD_ID`) and validate that it is present. Do not use the most recent saved thread or copy an ID from these examples. Resolve an ambiguous target before delivery.
- Resolve the real executable, working directory, OS, and Codex home. Read only the needed environment values, never dump credentials or whole environments. Timers do not inherit arbitrary shell environment: explicitly supply a custom `CODEX_HOME`, necessary PATH, and working directory.
- For a delay, record an absolute due time and timezone before setup. If setup takes time, use the remaining delay, not the original delay again. Distinguish elapsed awake time from a wall-clock deadline across sleep.
- A request to schedule authorizes that specific message and timer. A request to investigate or create this skill does not itself authorize notifications. Do not ask again for already-authorized routine actions; use the runtime's normal escalation mechanism when OS scheduler access requires it.

## Immediate delivery

Pass the message as one literal argument:

```sh
/absolute/path/to/codex queue --thread THREAD_ID --message 'User-authorized task text'
```

Use proper platform argument escaping or an argument-vector API. Never interpolate arbitrary message text into executable shell source. Include what the receiving agent should do and that this is a one-time scheduled request; do not instruct it to schedule itself again unless recurrence was requested.

Capture exit status, stdout/stderr, and the returned queued-item ID. `Queued message ... for thread ...` establishes registration, not execution or receipt. If the outcome is ambiguous, inspect evidence before resubmitting: another attempt may duplicate work.

## Delayed delivery

Read only the reference for the relevant OS:

- [macOS: launchd](references/macos.md)
- [Linux: systemd user timers](references/linux.md)
- [Windows: Task Scheduler](references/windows.md)

Prefer a unique, one-time OS-owned job with logs and an explicit cancellation path. A tool session's `nohup`, trailing `&`, `disown`, or detached subprocess is not proof of independence from its process cleanup. In the original macOS tool environment, `nohup` started but died before its delayed action, while a launchd job completed across tool returns. This is observed environment behavior, not a claim that nohup always fails.

For a new environment, a short harmless scheduled log write can establish that the OS job outlives the launching tool. Do not send extra live test messages without authorization. Do not automatically enable lingering, change power policies, install services, or configure remote access merely to make a timer work.

## Verify and report each stage separately

1. **Scheduled:** OS scheduler lists the expected job, due time/action, target, and log destination. A successful shell exit alone is insufficient.
2. **Queued:** the timer ran and the CLI acknowledged a queued-item ID with a successful exit.
3. **Executed:** the intended thread actually received the message and produced the requested response. Have a notification-test receiver read the current time and report it in the user's timezone.

Report only the stage observed. Before ending a scheduling turn, give the due time, what is registered, and relevant liveness conditions. Do not keep the originating turn alive solely to make an idle-thread test pass. After execution, retain useful logs and remove only the task's own scheduler registration. Cancelling a timer does not retract a message already queued.

## Diagnose a missing message

- **No scheduler registration:** setup failed; inspect the registration error.
- **Registered but not run:** inspect due time, timezone, login state, sleep, and scheduler status.
- **Process ran but queue failed:** inspect exit code and stderr, executable/wrapper dependencies, working directory, Codex home, and app-server access.
- **Queue acknowledged but no turn:** inspect the intended thread and its loaded/lifecycle state before retrying. A running turn may defer processing; interrupted, unloaded, or stopped threads need separate diagnosis.
- **Empty log:** does not prove queue acceptance or identify the killer. Check process/job status and use timestamp checkpoints in a harmless reproduction.

## Queue implementation and limits

The public `rust-v0.153.4` implementation stores queued items in SQLite and watches external changes. For a loaded eligible thread it can wake an idle thread, then calls `start_turn_if_idle`; successful start removes the queued item. “LLM must already be running” is not the design. The exact current build and desktop lifecycle may differ; check installed help and source when behavior disagrees.

An independent timer does not keep Codex alive. Use the same user/home and keep the receiving app-server alive with the target loaded for the straightforward workflow. Do not promise wake-up of a closed application, an unloaded thread, a powered-off machine, or delivery at an exact second.

Source pointers (version-specific; retrieve only when needed):
- [CLI queue command](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/tui/src/session_queue_commands.rs)
- [Queue watcher and idle dispatch](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/ext/queue/src/service.rs)
- [Persistent queue storage](https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/state/src/runtime/queued_items.rs)
