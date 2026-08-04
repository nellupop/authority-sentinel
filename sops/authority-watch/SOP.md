## Steps

1. **Check authorities** — Run this exact command using the shell tool, with no changes:
   `python "<absolute path to>/shared/skills/security/authority-watch/authority_diff.py"`
   Report back only the literal JSON it prints to stdout. Do not summarize,
   interpret, or invent results — paste the raw JSON output as your answer
   for this step.
   - tools: shell

2. **Alert** — Only if the JSON from step 1 has `"changed_count"` greater
   than 0, POST the `"summary"` field from that JSON to the Telegram Bot
   API's `sendMessage` endpoint for the configured chat. If `changed_count`
   is 0, do nothing and end the run.
   - tools: http_request

<!--
This SOP runs in `execution_mode = "auto"`, not `deterministic` -- see
SOP.toml for why. Confirmed working end-to-end via live daemon logs
(2026-08-03T18:05-18:07 UTC): the agent calls `sop_list`/`sop_status` to
orient, reads SKILL.toml, then calls the `shell` tool with the exact command
above, and the real output (`{"changed_count": 0, ...}`) comes back from a
genuine run against live Solana RPC. First few iterations were exploratory
(sop_status, file_read, glob_search) before landing on the right tool call --
harmless but wasteful; tightening the prompt text to be more directive is a
known follow-up, not a blocker.

Two things this file depends on that lived in SOP.toml, not here:
- `execution_mode = "auto"` + `agent = "sentinel"`: a bare cron trigger on
  the SOP engine's own headless dispatch never executes a non-deterministic
  step -- confirmed via repeated "no agent loop available to execute"
  warnings in `zeroclaw -v daemon` output. The actual trigger that works is
  a *separate* declarative `[cron.<id>]` job with `job_type = "agent"` and a
  `prompt` field in config.toml, claimed by the agent via
  `agents.sentinel.cron_jobs = ["<job id>"]` -- see config.toml.snippet.
- `risk_profiles.automated.gated_actions = []`: without this, every shell
  call parks on a `[Y]es/[N]o` approval prompt with nobody there to answer
  it, which is safe for interactive testing but defeats an unattended
  watcher.
-->
