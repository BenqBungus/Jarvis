# Verified local work and responsive task status

This iteration improves the existing task runner, not unrestricted autonomy.
Planning retains bounded decisions, cancellation and existing permission gates.

## Try it

- `File info Documents/Report.txt`: existence, file size and modification time.
- `Folder info Documents/Work`: existence and folder type, without reading contents.
- `Check path Documents/Absent.txt`: reports missing, not successful creation.
- `Create folder Documents/JarvisDemo`, then `Create file Documents/JarvisDemo/Notes.txt`.
- During a task: `Jarvis, what are you working on?` or `Task status`.
- In Realtime: request a project folder and notes file as one task. The existing
  planner uses the creation tools and requires configured API access.

Metadata inspection and deterministic local commands need no cloud model. The GUI
executor answers the exact task-status phrases without waiting behind queued work,
for typed and classic-voice commands. Realtime uses get_active_task_status.
Speech/audio availability is a separate prerequisite.

## Completion evidence

Folder creation checks existence and type after the operation. Text-file creation
checks existence, type and expected UTF-8 byte count. This is a point-in-time
metadata check, not a content hash, semantic quality check or guarantee against
later edits. It does not scan unrelated files or recursively measure folders.

Task results and the most recent GUI task status include bounded completion_evidence:

- verified: the tool supplied a positive supported completion flag; inspect its scope.
- not_verified: a completion flag was false or the outcome was uncertain.
- request_accepted: only a launch request was accepted.
- reported: success reported without a supported independent completion flag.
- failed: the tool failed.
- dry_run: a preview, not a completed operation.

A multi-step task stops after an unverified close request instead of proceeding
as though the app exited. It never automatically escalates to force termination.
The app may still be waiting for Save or remain in the tray; inspect it yourself.
Uncertain file creation does not trigger a retry or removal of the file. An adaptive
task cannot claim success without any tool observations, except an explicitly
labeled dry-run preview. This cannot prove every arbitrary natural-language goal.

Full access remains a one-time opt-in for eligible local actions. Inspection is
read-only. Network/device paths, private/system locations, links and cloud
placeholders keep their existing protections.

## Copy and Move Verification

Copy now hashes the bytes read from the source stream, checks source metadata
before/after copying, and reads the published destination to compare SHA-256 and
byte count. The destination must also remain stable during that read. This detects
same-size corruption; it is not a semantic document check or an OS-locked snapshot
against malicious timestamp manipulation. No content or digest value is added to
the result: the observation records size, timestamp and a hash-match boolean.
The existing 512 MiB and 60-second limits include destination verification.

Move/rename and move Undo verify that the old path is absent and the destination
has the expected filesystem identity. A reported rename request alone is not
success. Undo history is saved only after successful verification. A failed history
write is reported separately from a verified move.

If publishing was attempted but verification fails, completion_verified is false,
outcome_uncertain is true, change_completed is null, and retryable is false.
The workflow stops; files are not automatically removed or moved back. A user
replacement or source mutation is preserved for inspection. Dry-run transfers are
explicitly labeled previews and never claim completed changes.

## ZIP Verification

ZIP creation captures source-tree metadata, hashes file bytes while archiving,
checks the staged ZIP member list/types/sizes, reads every member through CRC
validation and compares SHA-256. It rechecks the source tree before publishing,
then reopens the actual published ZIP and repeats the content checks. The archive
observation includes entry/byte counts, match booleans and a timestamp, not file
contents or digest values.

Extraction keeps one source ZIP handle open and checks its identity/metadata before
and after processing. Each member is streamed with CRC validation and a content
hash. The staged and published extraction trees must have exactly the expected
files and directories, including empty/implicit directories, with matching file
sizes and SHA-256 hashes. Missing/extra paths and same-size corruption fail the task.

The existing limits remain: 512 MiB input/expanded content, 60 seconds including
verification, and 5000 output paths including implicit directories and the root.
ZIP nesting is capped at 64 levels. The central directory is bounded before the
standard ZIP parser loads it; split layouts, ZIP64 directory locators, encryption,
unsafe names and special paths are rejected. Unsupported archives fail normally.
These are point-in-time consistency checks, not malware scanning, authenticity
verification, document analysis or OS-locked protection against hostile concurrent
filesystem changes. A dry run checks the plan, not the full compressed contents.

Before publication, failure removes only Jarvis's private staging directory.
After publication is attempted, failure is explicitly uncertain and stops the
workflow without retrying or automatically deleting/restoring the destination.
Concurrent user-created destinations are never overwritten. Prepublication
cancellation/time-limit failures expose structured stop flags to the task runner.
Configured permissions and confirmation requirements have not changed.

## Bounded Recovery

Missing/unexpected arguments and incorrect argument types now return structured
error codes, executed=false and retryable=false. The same invalid request is not
retried. The existing adaptive planner can choose corrected arguments or another
approved read-only approach, but repeated failed calls remain blocked. Permission
checks still apply to every new action.

Retries honor the remaining adaptive task deadline before starting another call.
Cancellation, time-limit and explicitly non-retryable results stop retries. A tool
cancellation/time-limit result cannot trigger alternative planning. Stop/uncertain
flags are preserved in the overall task result, not only its nested step history.
An already-running synchronous tool cannot be forcibly interrupted by this change;
its own timeout/cancellation implementation still determines when it returns.

## Test limits

Tests use real temporary files and deterministic planner decisions, with mocked
process-close outcomes. They do not terminate user apps, listen to the microphone
or send paid model requests. Free-form planning and real audio still need testing
on the target laptop.

Previous Codex-owned regression selection: 166 passed, 1 skipped. It covers real
temporary copy/move/Undo, same-size corruption, source mutation, identity changes,
postcheck errors, dry-run evidence, workflow recovery, registry validation and
GUI executor/task-state compatibility. No live model or personal audio was used.
Claude-owned voice/UI files were not edited. The standalone ZIP was not rebuilt:
source must be frozen with Claude before full-suite verification and packaging.
Use the source launcher after restarting Jarvis to test this increment.

Latest ZIP increment: 196 passed, 1 skipped in the focused Codex-owned selection,
including 30 new archive tests. Real temporary archive roundtrips include empty
files/directories, Unicode names and multi-chunk content. Fault tests cover source
changes, wrong but readable ZIP contents, missing/extra extracted paths, staging
and published verification failures, output races, directory/depth limits, ZIP64
preflight rejection, cancellation/deadlines, dry runs, and workflow stop/evidence.
No personal documents, microphone capture or live model calls were used. This is
source-only validation, not a new full-suite run or updated standalone release.
