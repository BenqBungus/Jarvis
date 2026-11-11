# Desktop Agent Specification: Implementation Status

This document tracks the broad user specification received on 2026-09-12.
It is not a claim that all requested capabilities are complete.

Latest integration review (2026-09-15): see INTEGRATION_REVIEW_2026-09-15.md.
Claude's voice work was checked and the pending tool-error GUI connection completed.
The voice/integration selection passed 246 tests, execution selection 196 with one
skip, mobile mock client 74 plus typecheck. Real audio and phone-to-desktop control
remain unverified/unimplemented respectively; no new standalone package was built.

## Delivered in This Iteration

- Screen Chat can use the current screenshot together with explicitly selected
  project files, through a bounded model-driven read-only tool loop.
- Native project picker and consent, scoped source reading with line numbers,
  directory inspection and literal search by name/content/type/date/size.
- Visible read-operation history and cancellation between requests/reads.
- Tests use synthetic local projects and mocked API replies, not private files
  or a paid live diagnosis. Packaged QA also exercises a synthetic project.

## Existing Separate Capabilities

The repository already has file search, local file/folder operations, archives,
PDF/Word extraction, AI edit previews saved as new copies, task workflows and
system/browser tools. These are not all exposed in Screen Chat. Their presence
does not mean every natural-language task works reliably end to end.

## Still Needed for the Full Specification

Delivered on 2026-09-13: reviewed existing-file patches, conflict checks, durable
one-step content undo, Python/JSON syntax checks, explicitly approved real pytest
execution, and check results as follow-up diagnostic context. See PROJECT_CODING.md.
The user selected a PWA companion for Claude; its current contract is design-only.

Delivered on 2026-09-14: a bounded text-only repair session connects actual failed
checks to scoped AI diagnosis, a separately reviewed patch, and rerunning the same
check. Maximum two diagnoses and three checks; expiry, cancellation, conflicts and
failures stop the session. No personal screen or paid live API was used to validate
this iteration. Real local pytest fixtures and GUI tests use simulated model decisions.
Source verification: 1423 passed, 6 skipped, 2 third-party Python audio deprecation
warnings. This count is regression coverage, not a percentage of the specification.

Delivered next increment: reviewed creation of source files inside already-existing project
directories, including mixed edit/create proposals, exclusive no-overwrite publish,
durable identity-checked Undo and a missing-module repair/retest fixture. Model
decisions in the acceptance fixtures remain simulated; no paid live diagnosis is
claimed. Claude's PWA write scope remains separate and unchanged.
Source regression run after this increment: 1451 passed, 6 skipped, the same two
third-party audio deprecation warnings. These are not 1451 independently delivered
user features and do not establish an overall completion percentage.

Latest execution milestone (source only): copy content verification, move/rename
and move-Undo identity checks, structured non-retryable argument failures, and
deadline/cancellation-aware recovery. The focused Codex-owned regression selection
passed 166 tests with 1 skipped. See TASK_VERIFICATION.md for scopes and limits.
No Claude-owned source was changed and no new ZIP/full-suite release is claimed
until the concurrent voice work is frozen for integration.

Next source-only increment: ZIP creation/extraction now verifies actual archived
and extracted contents, including empty/implicit directories, CRC and SHA-256.
Concurrent source changes and uncertain published results stop the workflow;
existing output is never overwritten or automatically deleted. Cancellation and
deadline failures carry structured stop flags. Focused Codex-owned selection:
196 passed, 1 skipped, including 30 new archive tests with real temporary files.
No voice/UI-owned paths, live model calls or release packages were changed.
The checks establish file consistency, not malware scanning or unrestricted autonomy.

Still needed:

1. Broader repair/retest acceptance across real projects. The bounded loop now
   exists, but individual patches still require desktop review; unattended apply
   is not enabled.
2. Build/test profiles for Node.js and other toolchains, dependency installation,
   directory creation within project patches and richer multi-step rollback history.
3. Real live model-driven repair acceptance tests across several projects, not
   only a deterministic tool loop with mocked model decisions.
4. Wider search and semantic retrieval across separately approved roots;
   duplicate detection and context-aware organization with preview and undo.
5. Explicit upload/download destinations and audited external-service actions.
6. Real opt-in microphone, screen and model-assisted coding acceptance tests.

The new project scope does not enable arbitrary terminal access, silent destructive
actions, kernel access or continuous-video understanding. The current standalone ZIP must
be rebuilt after source changes before colleagues receive these additions.
