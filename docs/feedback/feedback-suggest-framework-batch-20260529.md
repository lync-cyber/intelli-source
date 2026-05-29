---
id: "feedback-suggest-framework-batch-20260529"
doc_type: framework-feedback
author: orchestrator
status: approved
deps: []
---

<!-- packaged by framework-feedback skill (manual assembly; cataforge CLI/gh unavailable in remote sandbox) at 2026-05-29T12:24:13+00:00 -->

# CataForge framework feedback batch — 5 suggestions from IntelliSource downstream (v0.4.1)

## Summary

Aggregated upstream feedback for the CataForge framework, distilled from the IntelliSource
project's backlog burndown. All five items concern the framework body itself
(`.cataforge/` agents / skills / scaffold / docs), not IntelliSource product code, and are
therefore better fixed once upstream than carried as per-project local edits that
`cataforge upgrade apply` would overwrite. Two previously-filed individual bundles
(an EVENT-LOG session-end bug and a reflector front-matter contract suggestion) are
referenced at the end and remain valid against 0.4.1.

## Environment

- **CataForge package**: `0.4.1`
- **Scaffold version**: `0.4.1`
- **Python**: `3.11.15`
- **Platform**: `Linux`
- **Runtime platform**: `claude-code`

## Proposals

### S1 — Default to a single source of truth (CLAUDE.md), make PROJECT-STATE.md optional

The scaffold ships a two-file state mechanism: `CLAUDE.md` (human-facing) plus
`.cataforge/PROJECT-STATE.md` (framework mirror). The two must be hand-synced — a real
double-write burden and a drift/inconsistency source. IntelliSource deleted
`PROJECT-STATE.md` and rewired four hard references (`framework.json` `migration_checks` /
`scaffold-manifest.json` / `self-update` SKILL.md / the state-persistence mechanism note),
designating `CLAUDE.md` as the single source of truth.

- **Risk that motivates upstreaming**: the next `cataforge upgrade apply` re-introduces
  `PROJECT-STATE.md` and reverts `migration_checks` from the upstream scaffold, silently
  overwriting the local decision. `cataforge upgrade rollback --from <ts>` recovers it but
  requires re-applying the four edits after every upgrade.
- **Proposal**: make the framework default to a single `CLAUDE.md` / `AGENTS.md` source of
  truth (drop the `PROJECT-STATE.md` double-write); **or** make `PROJECT-STATE.md` opt-in
  (`migration_checks` non-enforcing + `scaffold-manifest` marks it `optional: true`), so a
  project can disable it without fighting the upgrader.
- **Acceptance**: after upstream adoption, `cataforge upgrade apply` no longer re-introduces
  `PROJECT-STATE.md`.

### S2 — deploy-spec review template must require a real local-stack bring-up

The `deploy-spec` review template (`.cataforge/skills/doc-review/`) covers SBOM / promtool /
rollback plan / canary strategy, but neither r1 nor r2 forced the reviewer to actually run
the minimal stack (`docker compose up -d db redis migrate api`). IntelliSource's
PRE-DEPLOY-WALKTHROUGH later surfaced 7 deployment breakages, 5 of which (Dockerfile path /
README / dependency declaration / shebang / uvicorn invocation) would have been caught in a
5-minute real bring-up.

- **Proposal**: add a hard constraint to the deploy-spec dimension of `doc-review` —
  "before review, a human must bring up the minimal local stack; attach the log/screenshot
  to the review report" — and add a mandatory `## §X Local minimal-stack verification
  evidence` section to the deploy-spec template.
- **Acceptance**: the next deploy-spec review auto-prompts for this; `framework-review`
  checks that deploy-spec reports contain the evidence section.

### S3 — Framework-level assembly-gap lint (recurring EXP-005)

EXP-005 (assembly gap) recurred 5 times across IntelliSource sprints: a
`build_*_composition` wiring root declares a dependency but fails to inject it into the
downstream facade, and nothing catches it until runtime.

- **Proposal**: ship an assembly lint in the `code-review` skill (e.g.
  `lint_assembly.py`) that asserts every dependency a `build_*_composition` function
  constructs is actually passed into the facade(s) it builds. This is a generic
  composition-root invariant, valuable to any CataForge project, not just IntelliSource.
- **Acceptance**: a deliberately dropped injection makes the lint fail.

### S4 — Extend the anti-truncation (Mid-Progress Drop) contract to all sub-agent roles

EXP-006 / EXP-007 produced a "Mid-Progress Drop Contract" (a 4-step prompt that keeps a
stalled sub-agent from silently dropping work). It is wired into `implementer` and
`refactorer` AGENT.md and proved effective, but is missing from `reviewer`, `test-writer`,
and `debugger`. (IntelliSource just hit the failure mode this contract prevents: a
dispatched `refactorer` burned ~49k tokens / 30 tool-uses with zero edits, then stalled.)

- **Proposal**: add the same 4-step contract prompt section to
  `.cataforge/agents/{reviewer,test-writer,debugger}/AGENT.md`.
- **Acceptance**: a stalled sub-agent in any of those roles emits the contracted
  mid-progress checkpoint instead of returning empty.

### S5 — Provide a process to apply accumulated RETRO EXP learnings back to the scaffold

IntelliSource accumulated 6 EXP improvement points across sprint-1~7 RETROs whose
application decision was deferred, because there is no clean upstream channel to fold a
downstream project's validated learnings back into the framework scaffold (agents/skills).
S3 and S4 above are two concrete instances of this gap.

- **Proposal**: define a lightweight "EXP → scaffold" intake (the `reflector` learnings
  registry already produces `SKILL-IMPROVE-*.md`; give it a documented path to a
  framework-feedback bundle or upstream PR) so cross-project learnings don't stagnate as
  per-project deferred backlog.
- **Acceptance**: a project's RETRO EXP can be packaged and proposed upstream via a
  documented one-command path.

## Previously filed (still valid against 0.4.1)

- `docs/feedback/feedback-bug-eventlog-session-end-20260505.md` — EVENT-LOG session-end bug.
- `docs/feedback/feedback-suggest-reflector-frontmatter-20260505.md` — reflector
  AGENT.md §Output Contract says SKILL-IMPROVE / RETRO files have no YAML front matter and
  the indexer auto-skips, but `cataforge docs validate` / `cataforge doctor` flag them as
  orphan FAIL until front matter is added; align the contract and the
  indexer/doctor implementation.

## Submission note

This bundle was assembled manually: the remote execution sandbox has no `cataforge` CLI,
no `gh` CLI, and the GitHub integration is scoped to `lync-cyber/intelli-source` only, so
it cannot open an issue against the upstream `lync-cyber/CataForge` repository directly.
Submit by pasting the relevant section(s) into CataForge's
`.github/ISSUE_TEMPLATE/feedback-from-cli.yml`, or run
`cataforge feedback suggest --gh` from an environment that has the CLI and upstream access.
