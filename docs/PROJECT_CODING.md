# Reviewed Project Coding

## Desktop Workflow

1. Open Screen Chat, choose a project folder and accept read access.
2. Open the project changes control and enable Allow AI patch proposals.
3. Share screen and ask Jarvis to investigate the error and propose a fix.
4. Inspect the Patch tab. Apply patch requires separate desktop confirmation.
5. Python/JSON syntax is checked automatically on changed files. No code runs in
   this syntax check. Other languages are explicitly skipped, not reported valid.
6. For real Python tests, select a Python executable for that project, choose
   Python pytest and Run check. Approve the displayed execution warning.
7. Ask a follow-up screen question using the actual check result. Full stdout is
   local unless Include check output in AI context is separately enabled.

The model has a proposal tool, not an apply/execute tool. This is an assisted
diagnose/propose/review/apply/check loop, not unattended autonomous code execution.
There is no API-key sharing, package installation or arbitrary speech-to-shell path.

## Bounded Repair Session

With a project selected and proposals enabled, choose a check profile and press
Repair checks. No screen capture or active screen share is required. There must
not already be a pending patch. The session has its own explicit consent for
sending source excerpts and diagnostic output to OpenAI, independent of the
ordinary output-sharing checkbox. Declining does not start checks or AI calls.

Jarvis runs the selected check, diagnoses actual failures using scoped source
tools, and pauses at the Patch tab. Apply patch still requires desktop review.
After approval it applies the exact proposal and reruns the SAME selected check,
not just syntax. A remaining failure can trigger one more diagnosis and review.
It does not change the check command, install dependencies or select a new runtime.

Limits: two diagnoses, up to six paid model requests per diagnosis, three check
runs, and a 15-minute session expiry including review time. pytest retains its
120-second per-run limit and executes arbitrary trusted project code, NOT inside
a security sandbox. Inspect changes to tests and imports carefully before approval.
Environment failures, no tests, API errors, missing proposals, conflicts and repeat
patches stop the loop. Success means only that the selected check passed.

The status and report show check/diagnosis counts and action events. Manual checks,
Undo and new Screen Chat questions are blocked while a repair is active. Cancel,
closing the changes panel, or revoking the selected project stops future work and
discards pending proposals. An in-flight API request cannot be recalled and may
take up to its timeout to return. Already-applied edits or test side effects are
not automatically undone; the one-step Undo record remains available.

Local tests exercise real syntax/pytest failures, reviewed edits, successful
rechecks and Undo with simulated model decisions. This is not yet a live-model
acceptance test or unattended patch authorization.

## Patch Boundaries

- Existing files must be explicitly read before proposing exact replacements.
- New UTF-8 source files can be proposed after listing their existing destination
  directory. Missing directories, private paths, unsupported extensions, Windows
  reserved names and existing destinations are rejected. Directory creation is
  not part of this project-patch tool.
- Up to six files TOTAL (edits plus creations), twelve exact replacements,
  16,000 characters per new file, and 128 KiB of before/after bytes.
- Every source must still match the observed bytes at proposal and apply time.
- Python/JSON replacements must parse. This does not prove logical correctness.
- Diffs are displayed as text; no patch is silently applied by model output.
- Individual replacements use same-directory temporary files and atomic replace.
- New files are staged in the same directory and published using an exclusive
  hard link, which fails if the destination already exists. Filesystems without
  hard-link support fail closed; there is no overwrite fallback. Version-2 undo
  records include each created file's identity and hash. Older version-1 edit-only
  journals remain readable. Undo removes a created file only if both its contents
  and identity match; newer edits or identical-content replacements are preserved.
  Already-missing created files are accepted as removed. Existing destination
  directories are never removed. Apply and Undo both need explicit approval.
  A multi-file batch is NOT a single filesystem transaction. On failure, Jarvis
  attempts to restore its own changes without overwriting concurrent user edits.
- Original bytes are written to .jarvis-undo.json inside the approved project.
  This hidden file is excluded from AI project reads. It contains source backups,
  is not encrypted, and holds only the latest patch attempt.
- Undo survives reopening a project, verifies current hashes and refuses conflicts.
  It restores file contents, not every original timestamp or extended attribute.
  Recovery-needed status must be investigated; it is not a successful repair.
- Private paths, recognized credentials, reparse points and hard links remain
  excluded. These checks are not a security sandbox against malicious local code.

## Check Execution

Syntax checking parses eligible Python and JSON locally without imports. pytest
executes arbitrary project/dependency code with the user's Windows permissions.
It can read/write outside the project and use the network; only run trusted code.
Read permission and Full access do not replace the separate execution confirmation.

The selected external Python runtime must already have the project's dependencies
and pytest installed. Standalone Jarvis still needs no Python to run its own GUI,
but it does not bundle every possible project's development environment.

Tests start without a console, with shell=False and fixed arguments. The child
waits at a gate until assigned to a Windows kill-on-close job. Job ownership is
established before pytest starts. Timeout/cancel and normal completion close the
job so spawned child processes are not left running. This is lifetime control,
not a permission sandbox. Output is drained but retained only up to 64,000 bytes.
An allowlisted environment omits API keys/tokens, and recognized secrets in output
are redacted. The filesystem itself is not isolated from the test code.

The report includes actual exit status; nonzero exits, timeout, cancellation and
incomplete syntax coverage are never reported as a verified working application.
Each run uses a fresh temporary bytecode-cache prefix inside the project and
disables bytecode writes, so same-size edits cannot reuse a stale timestamp cache.
The temporary directory is removed after the owned processes stop; pre-existing
project caches are not deleted. This uses Python's documented
[-B and -X pycache_prefix options](https://docs.python.org/3/using/cmdline.html).
Cancel cannot undo changes already made by a test. Cloud analysis of test stdout
requires an extra opt-in because redaction cannot recognize all sensitive content.

## Verification

Automated fixtures cover preview-only proposals, scope escape, unread sources,
stale-source conflicts, rollback after a partial failure, durable undo, conflicting
undo, linked journals, syntax errors, GUI approval denial, output-sharing consent,
real passing/failing pytest child processes, timeout and descendant cleanup.
Creation fixtures cover mixed edits/new files, empty files, existing subfolders,
duplicate names, raced destinations, file identity conflicts, partial-publish
rollback, backward-compatible journals and a real missing-module pytest repair.
No personal project has been changed or sent to an API as part of these checks.
