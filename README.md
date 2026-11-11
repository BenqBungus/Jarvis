# Jarvis for Windows

A local Windows assistant with a native desktop interface, English conversation, OpenAI voice, explicit laptop actions, and background monitoring.

## Critical Conversation Screen Help and Reviewed Edits (2026-09-10)

Jarvis's chat and Realtime instructions now ask for independent, constructive disagreement: identify assumptions, give the strongest counterargument, distinguish evidence from opinion, acknowledge uncertainty and revise a view when warranted. Devil's-advocate roles should be labeled, not passed off as established facts. This is a behavior/prompt change, not a new reasoning model or proof that every debate answer is correct. Existing English-only voice remains unchanged. Try `Debate me about remote work. Challenge my assumptions, but change your mind if my evidence is stronger.`

### Screen help

Use the monitor icon in the header or say `start screen sharing`. After confirmation, an always-on-top indicator appears with a Stop button. Sharing is off on startup, expires after five minutes and requires a responsive GUI indicator. Ask `ask screen Why is this code failing?` or ask the Realtime model about the visible screen. Each question captures a fresh **primary-monitor screenshot**, sends it to OpenAI and returns an explanation. There is no periodic capture, continuous video, screenshot archive, remote control or direct Microsoft Copilot integration in this feature. It can discuss a visible Copilot response just like other visible content, not operate Copilot on the user's behalf. Hidden/unsaved portions of code cannot be inferred from a screenshot; choose the actual file for edits.

`stop screen sharing` and the indicator Stop button revoke future snapshots. Stop during an in-flight API request cannot retract an already-sent image; the old answer is discarded after return. The Realtime stop tool bypasses the GUI job queue. A missing/stale indicator heartbeat blocks capture. Native visibility/occlusion (including exclusive-fullscreen apps), microphone recognition, image comprehension and API access still need live testing. Close sensitive windows first: **screen images are not automatically redacted**. `store=False` does not guarantee zero provider retention. The older separately confirmed `screen_describe` tool keeps its existing screenshot behavior; the new sharing tools do not write images to disk.

### Edit together

```text
edit file "Documents/notes.txt" to make the introduction clearer and more concise
preview file edit
save edited copy to "Documents/notes-revised.txt"
discard file edit
```

New tools `propose_file_edit`, `preview_file_edit`, `save_file_edit` and `discard_file_edit` operate on an exact user-selected file. Proposal generation requires cloud-disclosure confirmation and returns a diff; the GUI opens a read-only preview. Saving requires a separate confirmation and a new destination filename. The original is always preserved, existing destinations are refused, and the proposal expires after five minutes. Source bytes are checked again before saving. This is **saving a revised copy**, not in-place editing, an IDE buffer integration or arbitrary app automation. Save any unsaved editor changes before requesting a proposal.

Supported: UTF-8 TXT/Markdown and common code formats (PY, JS/TS/JSX/TSX, CSS, HTML, JSON, YAML), at most 64,000 bytes with a bounded diff. PDF/Word editing is not included here; the document tools above can instead produce a new source-based Word draft. Private/config/linked paths, recognized credentials, oversized/binary content and malformed model responses are rejected. Python syntax and JSON parsing are checked where applicable; code is **never executed and no runtime test success is claimed**. Recognized secret detection is heuristic. Edited copies preserve UTF-8 BOM and the original dominant CRLF/LF convention. Proposals are temporary in-memory state, but diff/answer text may appear in the local audit/history and model context; discard is not deletion of those records.

### Sharing a beta

See [BETA_TESTING.md](docs/BETA_TESTING.md) for a clean source-beta package, tester installation steps and the work still needed before a public executable. **Never send the entire development folder or your API key.** Each tester needs their own key/billing and personal setup. No distributable ZIP or new installer was produced in this change.

## Read Discuss and Draft Documents (2026-09-10)

The source app now supports an explicit PDF/DOCX workflow, not just a blank Word outline:

1. Select one file, or search/list Downloads first to get its exact name.
2. Ask Jarvis to analyze it. Confirm sending extracted text to OpenAI.
3. Ask follow-up questions about its argument, evidence and weaknesses.
4. Request a source-based Word draft/chapter, providing its title, instructions, approximate length and destination filename. Confirm generation and saving.

Example Realtime conversation, using a file that actually exists:

```text
Analyze the PDF Research.pdf in my Downloads folder. Summarize it and tell me what you think.
What are the weaknesses in its argument?
Write a 1500-word thesis introduction about this study. Title it Plant Growth Analysis
and save it as Thesis Introduction.docx in my Documents folder.
```

Natural wording is interpreted by the configured model, so exact recognition/routing still needs a live microphone test. Deterministic commands are also available through voice fallback or the overlay:

```text
analyze document "Downloads/Research.pdf"
ask document What are the main weaknesses?
write document "Plant Growth Analysis" to "Documents/Thesis Introduction.docx" about critically assess the study
show document context
forget document
```

`local` prefixes avoid AI **routing**, not AI document analysis: analysis/discussion/writing still use OpenAI and require API access/billing. No source document has been sent to a paid API as part of development tests. Responses use the existing configured text model, not a new model/key; the existing Realtime session speaks the returned answers. No additional voice is installed by this change.

**New tools:** `analyze_document`, `document_context`, `ask_document`, `draft_document`, `forget_document`. The first and draft operations require confirmation in local routing, normal LLM routing, Realtime and workflows. Follow-ups reuse only the already-approved active document, identified by an observed opaque ID. A different file must be analyzed/approved again. Old/made-up IDs, changed source files, expired contexts and forgotten contexts are refused. One source and four recent document exchanges are held in process memory for at most 30 minutes of usability; expiry is cleared on the next context access, not secure timed memory erasure. Restart clears this context. Forgetting does not erase existing chat/audit/provider history or output documents.

**Reading limits:** PDF and DOCX only, up to 20 MiB; no legacy DOC, DOCM, encrypted PDFs or OCR. PDF text gets real page labels; DOCX body paragraphs/tables get block labels, never invented page numbers. Up to 60,000 extracted characters, 120 PDF pages or 2,000 Word body blocks. Word headers, footnotes, comments, revisions, text boxes and images are not fully covered. Scans without text fail clearly; mixed documents and truncated extraction report partial coverage. This is text analysis, not visual chart/layout understanding. A hidden helper receives an in-memory snapshot, with a 20-second extraction deadline and cancellation checks. It does not launch Word, execute embedded macros, follow source links or run source instructions. It is not an OS security sandbox or a guarantee against every malicious parser input.

**Privacy and evidence:** private/system/linked paths are rejected, recognized secret patterns are redacted before AI, and raw extracted text is not returned in tool metadata or persisted as a local content index. Redaction is heuristic, not anonymization. Selected text is transmitted to OpenAI after confirmation; answers and file metadata may appear in conversation/audit history. The analysis call has no tools and treats source contents as untrusted evidence. It is instructed to separate source claims from opinion, cite observed page/block labels, disclose coverage gaps and not invent references. These are model instructions, not proof that every generated claim is correct. Requests use `store=False`, which is not a claim of zero provider retention; see the [Responses API reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create). PDF text extraction uses [pypdf](https://pypdf.readthedocs.io/en/stable/modules/PdfReader.html).

**Writing limits:** one source-based draft/chapter per request, target 300-4000 words, actual word count reported. This is not an entire verified thesis, a literature review across unprovided sources, automatic submission, or an exact page/word guarantee. Existing output files are never overwritten. The user chooses an existing folder plus a new `.docx` filename; create the folder first if needed. The file is staged, reopened as a DOCX to check integrity, then published with Windows no-overwrite rename. Cancellation, a replaced source or competing destination prevents publication. AI calls time out at 90 seconds with no automatic retry; cancellation during a synchronous API request is checked when that request returns and cannot retract text already sent. A saved draft needs review for evidence, citations and layout. The old `create_docx` tool remains an outline-only helper and is now labeled accordingly.

Dependency: `pypdf>=6.18,<7` was installed in this workspace's virtual environment. Requirements and the `documents` extra declare it with python-docx/OpenAI. For another source installation use `pip install -e .[documents]`. Restart with `./run.ps1 --gui`; an already-running instance keeps its old tools. Document extraction deliberately refuses the old frozen installer; packaging this helper into Jarvis.exe remains separate work.

Verification: **1232 tests passed, 5 skipped**, with two existing audio-dependency deprecation warnings. Forty-one document tests cover real PDF/DOCX extraction, table order, coverage, encrypted/scanned/corrupt inputs, redaction, session IDs/expiry, source changes, hidden helper execution/cancellation, actual staged Word output, destination races, dry run, and confirmation in local/LLM/Realtime routes. OpenAI responses are mocked; no claim of live API quality or successful microphone/speaker operation is made. The sample draft reopened correctly. Visual rendering was attempted with the bundled document renderer but blocked because LibreOffice was unavailable, so generated page layout remains unverified.

## Search Inside Text Documents (2026-09-09)

Find a document by a phrase inside it, then choose a numbered result:

```text
Jarvis, find files containing gaming mouse in Documents
Jarvis, find files containing "project budget" in "Desktop/Podcast" type txt
Jarvis, show file results
Jarvis, open file result 1
```

The local command parser works without AI; prefix `local` in the overlay to explicitly use it. Use quotes when the phrase includes option words such as `in`, `type` or `after`, and for folder paths containing spaces. Realtime receives the optional `content` argument on `search_local_files`; it must ask for a folder if the user has not specified one. Without `content`, the existing search still reads names/metadata only. Name, extension, date and size filters can be combined with content matching.

This is **case-insensitive literal text search**, not semantic search or a regular expression. It recursively inspects only TXT, Markdown and CSV in the explicitly selected local folder. UTF-8 (with or without BOM) and UTF-16 with BOM are supported, including Bulgarian text. PDF, DOCX, archives, legacy encodings and other binary formats are not parsed. Search returns paths and file metadata, never excerpts or full document text. Numbered selection, identity rechecks, five-minute expiry and no-auto-open behavior apply unchanged. A listed match is an observation from search time, not a guarantee that the file still contains that phrase after later edits.

Bounds: at most 1 MiB per file, 16 MiB read per search, 25 matches, 12,000 visited entries and the existing three-second search deadline. Cancellation/deadline checks occur between entries and 64 KiB reads; an individual filesystem read can still take longer. Files that change during reading, oversized/unsupported files, access failures and excluded paths make coverage explicitly **partial**. A completed scan is not a whole-computer search. Content search refuses drive/home roots, system/private folders, dot paths, links/reparse points and common secret/config filenames. Documents with secret patterns recognized by the existing privacy detector are omitted after local inspection. These exclusions are conservative heuristics, not a guarantee that arbitrary personal documents contain no sensitive data. There is no persistent content index. File paths and match metadata can reach the voice model/audit log, but this tool does not return document contents.

Restart the source GUI to refresh its tools; no dependency, background service or API setting change is required. The installer is not rebuilt. Automated checks use isolated temporary documents and mocked Windows opening; live speech recognition and speaker playback are not verified by these tests.

Verification: **1191 tests passed, 5 skipped**, with two existing audio-dependency deprecation warnings. Thirty-eight new checks cover real content matching, encoding and chunk boundaries, explicit scope, privacy exclusions, byte/time limits, cancellation, unreadable/replaced files, combined filters, numbered selection, local commands and Realtime tool schema/execution. Existing name-only searches remain content-free.

## Choose a File Search Result (2026-09-09)

After searching, choose an observed result by number without dictating its full path:

```text
Jarvis, find files type pdf in Downloads
Jarvis, show file results
Jarvis, open file result 2
```

`Open the second file result` also works. These are local routes; the overlay accepts `local open file result 2`. Realtime receives `show_file_results` and `open_file_result(ordinal, search_id)`. The model must use the observed one-based ordinal and exact search ID, not invent them. A bare `open the second result` asks file-versus-web clarification when there is file-search context, avoiding accidental selection from the other result list.

The latest file list is held only in the current process, bounded to the existing 25 results, and selectable for five minutes. A new search, including an invalid, empty or cancelled search, invalidates old selections. Concurrent searches cannot overwrite a newer selection list with an older one. Partial results remain explicitly partial; approximate matches remain suggestions and are never auto-opened.

Before opening, Jarvis checks the path and parent components again and compares the file ID, device, creation time and type recorded during search. Missing/replaced files, links/cloud placeholders, changed search IDs and expired selections are refused. Existing document-type restrictions remain in force, including blocked executables, scripts and shortcuts. Metadata returned to callers cannot alter the private selection list. Ordinary edits to the same file do not restore old contents or invalidate its identity. This is a checked path-based Windows open request, not an atomic handle-based security boundary against concurrent filesystem changes.

Success means Windows accepted the open request, **not proof that a visible application window appeared**. Search and list commands never open anything. No new background service, installation or persistent file index is introduced. Restart the source GUI and perform a fresh search to use these tools; the installer is not rebuilt by source edits.

Verification: **1153 tests passed, 5 skipped**, with two existing audio-dependency deprecation warnings. Twenty-eight new tests cover ordinal selection, stale/invalid/expired search IDs, replaced/missing files, executable refusal, cancellation, dry runs, metadata isolation, competing searches, local commands, web/file clarification and preservation of the existing recent-file command. Tests use real isolated filesystem entries and a mocked Windows launch call; live microphone recognition and visible app opening remain for a user check.

## Observed Laptop and Driver Inventory (2026-09-09)

The new read-only `device_info` tool reports the actual Windows-reported manufacturer/model, CPU core/thread counts, all returned graphics adapters, physical memory visible to Windows, motherboard, BIOS version and Windows build. It queries allowlisted CIM properties and excludes serial numbers, UUIDs, account names and product keys. Missing sections/fields remain unavailable, not guessed from a configured Acer model. Identity is queried only on request, not added to the startup greeting or a new background service.

`driver_info` and `nvidia_driver_info` now return structured device records instead of a potentially truncated console table: name/class, installed Windows driver version, package date, provider, manufacturer, INF and signature flag. Both are read-only `safe` tools, not administrator actions. Categories are all, display, NVIDIA display only, chipset-related components, audio, network and Bluetooth. Chipset selection is explicitly a device-class/name heuristic, not a complete chipset package inventory or one unified version. Inventory reads at most 1000 records and displays at most 100 matches, reporting partial coverage when limited or versions are missing.

```text
Jarvis, what laptop do I have?
Jarvis, show BIOS version
Jarvis, show chipset drivers
Jarvis, show network drivers
Jarvis, what is my NVIDIA driver version?
```

These are deterministic local routes and Realtime tools. The overlay also accepts `local show device info` or `local show installed drivers`. Restart the source GUI to refresh its tool definitions. No new dependency or elevated helper is required; failed CIM reads are reported normally rather than requesting elevation automatically.

**This does not check for a newer driver, validate compatibility or install anything.** A Windows driver version is not necessarily the NVIDIA release label. Package dates are not installation dates; an old date alone does not show that a driver is outdated. An `oem*.inf` filename or provider name is not proof of Acer OEM origin. Online OEM comparison, update release notes, restore points and confirmed installation remain separate work. Windows Update checks already available in Jarvis remain unchanged.

Real-device read-only verification identified Acer Nitro ANV15-51, Intel i7-13620H (10 cores/16 logical processors), RTX 4050 Laptop GPU and Intel UHD Graphics. It also returned BIOS V1.60, the installed Windows NVIDIA driver version 32.0.16.1088 and ten chipset-related component records at the time of testing. Nothing was installed, closed or reconfigured. The implementation uses Microsoft's [computer-system CIM fields](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-computersystem) and [signed-driver fields](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/whqlprov/win32-pnpsigneddriver).

Verification: **1125 tests passed, 5 skipped**, with two existing audio-dependency deprecation warnings. Thirty-six new tests cover structured identity, multiple GPUs, missing/malformed data, sensitive-field exclusion, driver categories, limits, read-only local routing and Realtime schema exposure. Helpers were checked for hidden/non-interactive execution and bounded timeouts. Live microphone recognition of the new phrases remains untested.

## File Search Filters (2026-09-09)

`search_local_files` now combines a name fragment with extension, file/folder kind, inclusive minimum/maximum file size, and inclusive local **modification dates**. Dates use `YYYY-MM-DD`, not creation dates. Exact-name matching includes the extension; fuzzy matching suggests approximate names with an explicit label and match scores. Results include absolute paths, sizes in bytes and modification timestamps. No contents are read and no result is automatically opened. Choose an observed path with the existing `open_local_path` tool; multiple matches must not be treated as an unambiguous choice.

The filters are exposed to Realtime voice and have deterministic local syntax:

```text
Jarvis, find files type pdf in Downloads
Jarvis, find folders named "Podcast" in Desktop
Jarvis, find files matching "podcst" in Documents
Find files type pdf after 2026-09-01 before 2026-09-09
Find files type mp4 min 100 MB max 2 GB in "Desktop/Podcast"
```

The overlay accepts these without `Jarvis`; prefix `local` to explicitly avoid cloud parsing. Options can appear in any order: `named`, `matching` (fuzzy), `type`, `in`, `after`, `before`, `min`, `max`. Quote names and paths containing spaces. Local KB/MB/GB use decimal units (1000 bytes per KB). Voice tool calls use whole bytes. Invalid/duplicate filters are rejected, not silently ignored. Extension and size filters apply only to files; folder sizes are not recursively calculated.

Scope remains Desktop/Documents/Downloads/Pictures by default or one explicit accessible local folder, now also accepting known-folder subpaths such as `Desktop/Podcast`. **Full-drive discovery, content indexing and date/size sorting are not implemented by this change.** Searches are breadth-first, normally bounded to 12000 entries, 25 results and three seconds, and report partial coverage when limits, inaccessible/excluded directories or linked paths are encountered. Queued directories are revalidated before traversal. Cancellation retains already observed partial results and never reports a complete search. Limits bound traversal checks; a single OS directory operation may still take longer on a slow drive.

Verification: **1089 tests passed, 5 skipped**, with two existing audio-dependency deprecation warnings. Forty new tests exercise actual files in isolated Windows test directories, inclusive dates/sizes, combined filters, typo suggestions, invalid inputs, cancellation, partial scope, no content reads/auto-opening, local command routing and Realtime tool-schema exposure. Live spoken recognition has not been tested for these phrases. Restart the source GUI to load the updated tool definitions.

## CPU/GPU Status and Thermal Sensors (2026-09-09)

Say `Jarvis, CPU usage`, `Jarvis, temp`, `Jarvis, GPU temperature` or `Jarvis, show hardware status`. Exact phrases are local, read-only routes, also available as `local cpu usage` without cloud intent parsing. Realtime can call the registered `system_hardware_status` tool. The report contains CPU usage, RAM usage, the first NVIDIA GPU's usage/temperature, hottest exposed CPU sensor, timestamp and explicit missing-sensor metadata. The GUI adds a CPU TEMP row; partial GPU readings no longer hide a valid temperature when utilization is unavailable.

CPU usage is sampled with psutil over 100 ms, including on a worker's first call. CPU/RAM refresh every two seconds, NVIDIA GPU every five seconds and CPU temperature every ten seconds, plus query time. CPU and GPU share the existing configurable temperature-warning threshold; each warns once per hot episode. Missing readings replace displayed values with unavailable instead of reusing a previous value. These are polled observations, not a thermal safety controller.

CPU sensor integration reads an **already configured** LibreHardwareMonitor local `http://127.0.0.1:8085/data.json` endpoint, with no redirects/proxies, bounded response size and timeouts. It selects numeric `RawValue` readings under CPU temperature sensor identifiers, excludes distance-to-TjMax/limit/offset sensors and reports the hottest valid sensor. Older LibreHardwareMonitor/OpenHardwareMonitor WMI providers are a fallback. ACPI thermal zones are deliberately not treated as CPU core/package temperatures. No monitor, driver, service, fan control or firewall change is installed or enabled by Jarvis.

The current laptop's RTX 4050 readings were verified live; **no CPU temperature provider was available**, so CPU temperature remains unavailable until a provider is configured separately. Modern LibreHardwareMonitor removed WMI; see its [official release notes](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases) and [local API implementation](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/blob/master/LibreHardwareMonitor.Windows.Forms/Utilities/HttpServer.cs). This integration does not start its web server: review network exposure separately before enabling one, since the provider also has control endpoints. Do not expose it to the LAN or open firewall ports just for Jarvis. Jarvis only requests the fixed read-only loopback data endpoint. Provider-supplied freshness cannot be independently verified, and sensor support depends on hardware and provider permissions. NVIDIA values come from [nvidia-smi](https://docs.nvidia.com/deploy/nvidia-smi/index.html); utilization need not match Task Manager's chosen GPU engine.

Verification: **1049 tests passed, 5 skipped**, with two existing audio-dependency deprecation warnings. Coverage includes missing/invalid sensors, partial GPU data, CPU sampling, loopback restrictions, provider fallback, hot-episode notifications and English/local command routes. GUI renders were inspected at 1360x850 and 900x660. Live microphone interaction and a real CPU temperature provider remain untested. Restart the source GUI after exiting the previous instance to load these changes.

## Undo for Rename and Move (2026-09-09)

Successful `rename_local_path` and same-drive `move_local_path` operations now save an entry in the existing Undo Center. Choose Undo Center or say **"Undo last action"** and confirm. The exact phrase also works locally with `local undo last action`, without cloud intent parsing. The local confirmation includes the recorded paths and binds to that history entry; a newer action during confirmation requires another review.

Undo restores the original path only when the moved file/folder still has the recorded filesystem identity, the original parent exists and the old path is vacant. It rechecks protected paths and links, never overwrites, and retains failed undo entries. Identity uses the Windows file ID, device, creation time and object type. Filesystems without a file ID are refused for these moves. This is **path undo, not a content backup**: edits to the same file and changes inside the same folder are preserved, not reverted. Replacing a file with an editor's save-by-replacement can therefore require manual recovery.

History persists across restarts, holds the last 50 reversible actions and is processed newest first, including volume/power/network actions. Undo does not add an inverse entry. Dry runs and failed moves add nothing. If a move succeeds but saving its history fails, Jarvis explicitly reports the completed move and unavailable undo. It similarly reports a completed restore if history cleanup fails. Copy, ZIP, file creation and process termination do not gain automatic undo in this update.

Try with disposable files, confirming each change:

```text
Create folder Jarvis Undo Test on Desktop
Create text file Desktop/Jarvis Undo Test/Notes.txt with content Hello Berk
Rename "Desktop/Jarvis Undo Test/Notes.txt" to "Plan.txt"
Undo last action
```

The last command restores `Notes.txt`. Restart the source GUI with `.\run.ps1 --gui` after exiting the previous instance from its tray menu. The packaged installer has not been rebuilt.

Verification: **1014 passed, 5 skipped**, with two existing Python audio-dependency deprecation warnings. Twenty new cases cover reverse-order recovery across service restarts, replaced files/folders, destination collisions and races, preserved edits, missing paths, cancellation, confirmation denial and changed history, dry runs, malformed records and history I/O failures. All file mutations were confined to isolated test folders. Live microphone-to-undo interaction was not tested.

## Local Drives, ZIP and Background Tasks (2026-09-08)

The user explicitly approved broader local-file access. New confirmed tools now accept absolute local paths and `Desktop/...`, `Documents/...`, `Downloads/...`, `Pictures/...`, using Windows' known-folder locations. This supersedes the earlier workspace-only limitation **for these new tools**; legacy workspace tools remain scoped. No administrator rights, ACL changes, permanent service or blanket permission bypass is installed.

- `create_local_folder`: create nested folders at the requested location.
- `create_local_file`: create an empty or UTF-8 text file, up to 1 MB. Existing files are never overwritten; the parent folder must already exist. This does not generate valid Word/PDF content merely by changing the extension. Existing DOCX generation can be followed by a confirmed move.
- `rename_local_path`: rename a file/folder within its parent, preserving the extension when requested. No overwrite; successful changes are now recorded in Undo Center (see above).
- `move_local_path`: move a file/folder within the same drive, to a full new path. Cross-drive moves are refused. Sources are not recursively copied/deleted.
- `copy_local_file`: copy one file to a new full path, including another local drive. Folder copies are not yet implemented; ZIP supports folder contents.
- `create_zip` / `extract_zip`: create a ZIP from a file/folder or extract into a fresh folder. Output parents must exist; creating an archive inside its own source is refused. Limits are 5000 entries, 512 MB and 60 seconds. Split/ZIP64/encrypted archives and central directories over 4 MB are refused. Links, path traversal, conflicting Windows filenames and protected/private paths are rejected. Extracted files are never automatically executed.
- `list_local_folder`: show up to 100 names without reading contents.

All new filesystem mutations require the existing confirmation dialog showing the supplied paths. Copy/ZIP outputs are staged beside the destination and published with Windows' no-overwrite rename only after success. Cancellation and failures clean up staging, leaving existing destinations untouched. A completed move/rename is not undone by cancellation. System installation/data directories, private configuration, network/device paths, alternate data streams, junctions/symlinks and cloud-placeholder paths remain protected. Ordinary files on other local drives are supported subject to the current Windows account's access rights.

Process access now includes **current-user background tasks**. Ask `Show processes for Discord` or `Show background tasks`. Select an exact PID when multiple force-stop targets match. The local normal-close route selects a unique visible matching application instead of its hidden helpers; multiple visible matches still require a PID. `end_process` checks current service membership as well as identity/owner/critical status before force-stopping; services, Jarvis, critical/system/security processes and NitroSense remain protected. Failed service inspection leaves the listing read-only. `close_app` still needs a visible window and never silently escalates to a force-stop. These APIs inspect Windows processes directly; Task Manager need not be open.

`open_task_manager` opens the Windows Task Manager for manual inspection. `launch_installed_app` resolves Start Menu names and asks for clarification when ambiguous. The voice `open_application` tool now requires confirmation and accepts a known alias, installed name or existing local `.exe`, **not arbitrary shell commands or arguments**.

Restart `.\run.ps1 --gui`, press Play, and speak in English. These examples also work in the local command overlay:

```text
Open Task Manager
Show processes for Discord
End process <exact PID from the list>
Open installed app Steam
Create folder Jarvis Test on Desktop
Create text file Desktop/Jarvis Test/Notes.txt with content Hello Berk
Rename "Desktop/Jarvis Test/Notes.txt" to "Plan.txt"
Copy "Desktop/Jarvis Test/Plan.txt" to "Documents/Plan Copy.txt"
Zip "Desktop/Jarvis Test" to "Documents/Jarvis Test.zip"
Unzip "Documents/Jarvis Test.zip" to "Desktop/Restored Test"
```

Keep quotes around both paths for deterministic overlay rename/copy/move/zip/unzip commands. Prefix `local` to avoid AI routing. Free-form voice uses the same registered tools and confirmation gates. No personal application was stopped and no real Desktop files were changed during development tests; external-path tests use sibling folders inside the isolated diagnostic workspace.

Verification: 994 tests passed, 5 skipped. Coverage includes external-path creation, rename/move/copy, ZIP round-trip and malformed/hostile entries, cancellation cleanup, destination races, service protection and no-shell app launches. Creating a real test symlink was unavailable; the reparse-attribute refusal was tested separately. A read-only Discord process inventory verified service inspection on this laptop. Live microphone-to-tool interactions remain for a user test.

## Normal Close Before Force Stop (2026-09-08)

`close_app` is now distinct from `end_process`. Say **"Close app Discord"**, **"Close Notepad"** or **"Quit app Steam"** for a normal close request. Say **"End process <PID>"** or **"Force close <exact process name>"** only when force-stopping is intended. Both operations require confirmation and a fresh observed process selection. Ambiguous names still require choosing a PID. These tools are available to Realtime voice and the local overlay after restarting the source app.

Normal close uses Windows [WM_CLOSE](https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-close) through [PostMessageW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-postmessagew). It targets visible, enabled, unowned main windows belonging to the selected process. It skips owned dialogs and disabled parent windows, does not click Save/Discard, does not broadcast messages, and never escalates to termination. Applications decide how to handle a close request; preservation of unsaved work is not guaranteed by every app.

Jarvis waits up to three seconds to verify process exit. If the app stays open, refuses, needs a Save decision, or remains in the tray, it reports **close requested, exit not verified**, not "closed". Partial failures retain the count of submitted requests in audit metadata. A later force-stop needs another selection and confirmation. Existing protections for Jarvis, critical/system/security processes and NitroSense remain in place. Browser tab and call-closing requests are not intercepted by the new local app-close parser.

Verification: 957 tests passed, 4 skipped. Tests cover normal versus forced close, confirmation denial, identity revalidation, pending Save dialogs, partial delivery and exit-verification errors. A real WM_CLOSE was delivered to a disposable zero-area Windows test window; no personal application was closed. Live spoken requests and third-party apps' Save behavior still need a user test.

## Processes and Workspace Files (2026-09-08)

New tools are available to Realtime voice and the deterministic local command path:

- `list_processes`: defaults to visible current-user desktop apps, or searches by process name/PID. Reports memory usage and short-lived selections, at most 50 rows. A partial result requires a narrower query.
- `end_process`: force-ends one selected desktop app **after confirmation**, then verifies exit. This may lose unsaved work and cannot be undone. It does not kill process trees or cancel Jarvis's own work. Selections expire after 120 seconds, are single-use, and revalidate PID creation time, owner, executable, visible window and Windows critical status. Jarvis, its ancestors, core Windows/security processes and NitroSense are excluded. Hidden/tray-only apps and services are read-only in this version. Close normally from the app when work needs saving.
- `cancel_task`: stops Jarvis's current workflow; the GUI also cancels queued work and pending confirmations. This is different from ending a Windows application. An OS operation already in progress may finish, and completed changes are not undone.
- `create_folder`, `create_file`, `create_text_file`, `list_folder`: create nested folders, empty files or UTF-8 text files, and list up to 100 names. Paths stay inside the Jarvis workspace, spelling/case is preserved, Windows-invalid names are rejected, and existing files are never overwritten. Text content is limited to 1 MB. Errors and file/folder collisions return a normal failure result.

Example English voice requests after restarting `.\run.ps1 --gui` and starting a live call:

```text
Show processes for Discord.
End process <the PID from the list>.
Cancel current task.
Create a folder called Projects/My Notes.
Create text file Projects/My Notes/Ideas.txt with content Remember to test Jarvis.
List folder Projects/My Notes.
```

The same exact commands work in the command overlay; prefix `local` to keep them offline. With multiple matching processes Jarvis asks for an exact PID instead of choosing. The process confirmation includes the observed app name and PID; results and confirmation decisions use the existing audit path. File creation outside this workspace still needs separate approval; arbitrary shell execution, automatic termination of background services and automatic document overwriting are not enabled.

Process termination uses [psutil's PID-reuse checks](https://psutil.readthedocs.io/stable/index.html) and a fail-closed [Windows critical-process check](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-isprocesscritical). The new tests include a disposable child-process termination with real Windows identity/critical/exit checks; only its visibility is injected for headless testing. No personal apps are stopped by the tests. Existing installer executables are not rebuilt by source changes.

Verification: 927 tests passed, 4 skipped, including process selection expiry/reuse, confirmation denial, ambiguous names, protected apps, cancellation queue bypass, file collisions and no-overwrite checks. A read-only inventory was also run against this laptop. Live microphone-to-tool behavior still requires a user voice test.

## Say Jarvis to Interrupt (2026-09-07)

During a **live Realtime call**, say **"Jarvis"** while a reply is playing. Local keyword recognition requests the same cancel-and-truncate operation as **Interrupt reply**: buffered speech stops, late audio is discarded, and the call stays open. It does not cancel an already-running computer task or undo an action. Wait for LISTENING, then ask your next question in English. In speaker mode leave a short pause after the name so the echo tail can clear; a whole question spoken over the reply is not replayed to the model.

This uses PocketSphinx on the existing microphone PCM stream, not a second microphone or a permanent service. In **Speakers** mode, reply-time microphone audio stays local for keyword detection while the cloud receives silence. The header shows **LOCAL WAKE / JARVIS**. **Mute** disables local keyword recognition as well as cloud input; queued detections are invalidated. Ending the call stops the keyword worker. No raw microphone recordings are saved. The speaker reference reduces self-triggers but is not acoustic echo cancellation: loud music, room echo and accent can still affect detection, and saying the name at the same time as Jarvis says it may be rejected. The interrupt button remains available; **Headphones** retains ordinary full-duplex VAD interruption.

Launch the source version with `.\run.ps1 --gui`. The launcher now prefers the workspace `.venv`, where the local keyword dependency has been installed. A new setup can use:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[voice,gui]"
.\run.ps1 --gui
```

If the optional decoder cannot load, the call still works and displays a fallback warning. No installer executable was rebuilt. To remove the optional feature from this environment, run `.\.venv\Scripts\python.exe -m pip uninstall pocketsphinx`; the button and headphone interruption remain available.

Offline diagnostic: `.\.venv\Scripts\python.exe tools/check_keyword_interrupt.py --stream` checks cached synthesized phrases, overlapping user speech and delayed speaker echo without recording or playing audio. `--generate` makes paid TTS requests only if a fixture is missing. These synthetic checks do not replace testing Berk's microphone and room.

Verification: 889 tests passed, 4 skipped. Cached phrase and paced mixed-audio/echo checks passed. Native Qt screenshots rendered at 960, 1360 and 1920 pixels; the speaking state displays the local keyword privacy indicator.

## English-Only Voice (2026-09-07)

The current conversation profile is **English only**, as requested. Realtime replies, English transcription hints, classic Google recognition defaults, startup greeting and speaker tests now use English. The greeting is "Hello Berk, how can I help you?" and the voice profile displays English rather than Auto-detect / BG + EN. Existing Bulgarian command aliases and saved history are preserved; they no longer select the live response language. Older dated sections below describe the previous bilingual profile.

Start `.\run.ps1 --gui`, press play, wait for LISTENING, and say "Hello Jarvis" or "How are you?". Follow with "Open https://plasico.bg" or any ordinary English question. The voice remains Cedar and the speaker/headphone echo settings are unchanged. An English-only profile does not guarantee perfect recognition or eliminate acoustic echo.

`python tools/check_realtime_connection.py --conversation --audio-greeting` now tests English synthetic speech, semantic VAD, follow-up memory and safe tool intents. The API accepted the configuration and returned English audio. This diagnostic does not record the microphone.

Verification: 872 tests passed, 4 skipped. The current transcription model receives `languages: ["en"]`; supported legacy models receive `language: "en"`, following the [OpenAI transcription documentation](https://developers.openai.com/api/docs/guides/speech-to-text). Language hints guide recognition rather than acting as an absolute language filter.

## Greeting and Echo Fixes (2026-09-07)

- Settings > Voice > **Live audio mode** defaults to **Speakers**. During Jarvis playback, outgoing microphone packets are replaced with silence until the speaker buffer and a short echo tail finish. This is half-duplex echo prevention, not acoustic echo cancellation: wait for the reply, or click **Interrupt reply** (skip icon) and then speak. With actual headphones, choose **Headphones** for full-duplex voice interruption. Reconnect the call after changing this setting.
- **Interrupt reply** stops speech without ending the call or cancelling a computer task. Cancel task remains a separate control. Late interrupted audio and captions are discarded.
- Startup TTS and Realtime no longer introduce Jarvis back-to-back. Queued classic speech is discarded on entering a live call, so it cannot play unexpectedly when the call ends. Bulgarian is the default; greetings should be brief, without repeated enthusiastic fillers.
- Every pytest test now uses its own temporary workspace and no inherited API key. The suite can no longer fill the real history/settings/undo files with fixture data. `tools/repair_test_conversation.py` previews known September 6 fixture records; `--apply` requires Jarvis closed, makes a backup, and preserves other records. It is a one-time repair, not a filter on future conversations.

Run `.\run.ps1 --gui`, press play, wait for **LISTENING**, then say `Здравей Джарвис`. No wake phrase is needed for follow-up questions. `python tools/check_realtime_connection.py --conversation --audio-greeting` checks synthetic Bulgarian audio through semantic VAD and spoken API replies without opening a microphone. It makes paid API requests; real room acoustics and audibility still require a local listening test.

## Control Layer (2026-09-06)

Alt+Space opens the new native command overlay without activating a microphone. The header keyboard/history/undo icons open the same controls. Ctrl+Space push-to-talk remains available. Local mode runs supported commands without AI; Teach supplies local instructions without performing actions. Activity & Undo shows recorded reasons, confirmation/evidence, failed-undo retention and repetition suggestions that never enable themselves.

Gaming has no default app-closing list. Volume now supports current/legacy pycaw and checks actual read-back. Unsolicited monitor speech is disabled by default. These are additions to the existing assistant, not full NitroSense thermal automation, global offline/privacy mode or completion of the entire requested specification.

See [the implementation report](docs/CONTROL_LAYER_2026-09-06.md) for examples, permissions, device checks, changed files, remaining work and the pre-edit source backup. Local mode is per command; it does not stop a live Realtime call already in progress.

## Background Windows and Live Task Controls (2026-09-06)

- Internal GPU, battery, driver, app-index and PowerShell helpers run without allocating a console window. PowerShell is non-interactive, stdin is disconnected, and subprocesses have bounded timeouts. This fixes the recurring console flash from periodic checks. Apps and websites explicitly opened by the user remain visible. Required action-confirmation dialogs remain enabled.
- During a GUI Realtime call, ask `Докъде стигна със задачата?` to read the actual current step, elapsed time and last result. The safe `get_active_task_status` tool and `cancel_task` bypass the action queue, so they remain available while another tool is working. Status is observed locally, not invented by the voice model.
- Say `Спри задачата` or use the cancel icon. Cancellation rejects pending confirmation dialogs and drops queued actions. An OS/API operation already in progress may finish before cancellation takes effect; completed actions are not undone. Shutdown rejects late confirmation requests instead of leaving workers waiting for a closed UI.
- Tool outputs are returned while conversation continues. Spoken tool summaries wait while the user or another model response is active; a response collision no longer ends the call. Interrupting speech alone does not cancel a computer task.

The live voice uses the official [OpenAI Realtime API](https://developers.openai.com/api/docs/guides/realtime-conversations), with the configured API voice and Jarvis tools. It is not an embedded ChatGPT consumer interface. API access and billing are separate from a ChatGPT subscription.

## Voice-First UI (2026-09-06)

Quit the old copy from its tray menu, then run `.\run.ps1 --gui`. Source edits do not rebuild the installer.

- The native main window now contains only System Status, Readiness, a large animated core, and minimal voice controls. Conversation, Tasks, Quick Actions, Modes and navigation panels are removed from the main window. Their backend tools and audit logging remain available.
- The central play button starts a continuous OpenAI Realtime call. It greets you if startup has not already done so. Talk normally without repeating a wake phrase. The same button ends the call and requests cancellation of pending actions. Cancellation cannot undo completed actions or instantly interrupt every running OS/API operation.
- The pause icon mutes outgoing microphone audio while replies can continue playing. Queued pre-mute speech is discarded even after unmuting. The separate cancel icon cancels a current task without ending the conversation.
- The core shows connecting/listening/thinking/speaking/error states. Waveform amplitude uses actual input and speaker PCM, not random animation. Rendering pauses when the window is hidden.
- A single temporary caption shows the latest heard phrase, reply or action result, not a chat history. Errors persist; hover to read the complete detail. Startup does not launch a hidden wake-word listener. The MIC indicator distinguishes off, live streaming to OpenAI, and paused input.
- Settings opens as a separate dialog. Live model/voice changes apply on the next call. Classic STT/TTS provider changes still need a restart. Settings > Audio contains voice/tone tests, diagnostics and the optional classic fallback. The central button always uses Realtime.
- Readiness checks prerequisites, not account credit or guaranteed device availability. Actual API/device failures are reported when connecting. Select the desired speaker/headset in Settings > Voice. Headphones are recommended for the initial test; this WebSocket client does not implement acoustic echo cancellation.
- Ask casually in Bulgarian or English, ask follow-up questions, or request an arbitrary public HTTP(S) URL. `open_url` uses the configured browser (Opera GX when configured). Interactive page tasks use the managed browser and retain confirmations. Login requirements, CAPTCHAs and inaccessible sites are not bypassed.

`python tools/render_voice_ui.py` generates native screenshots with fixture readings at 960/1360/1920 pixels without microphone/network access. `python tools/check_realtime_connection.py --conversation` makes small paid API requests to check generated speech, synthetic Bulgarian conversation context, an arbitrary-URL tool intent and a spoken response to the GUI's read-only task status. It does not record the microphone or perform computer actions; the safe status read is audited under `data/diagnostics/`. Real microphone recognition, echo and speaker audibility still require a local listening test.

## Autonomy Update (2026-09-05)

Start the source app with `.\run.ps1 --gui` and speak a goal in the live call. The cancel icon can cancel the current task and queued commands, including rejecting a pending confirmation. Cancellation is cooperative: a running browser/API operation must return before execution stops; completed actions are not undone.

- Explicit `agent mode ...`, `сам реши стъпките ...`, or `адаптивно ...` requests use result-driven planning, with up to 8 decisions and a 180-second budget checked between operations. Planning requests have a 45-second timeout. The model receives page text, real control references and tab IDs, not just an "opened" message.
- Live voice has `run_autonomous_task` and `cancel_task` tools. The GUI stop control remains available without waiting behind the command queue.
- Playwright now opens a separate managed browser profile under `data/browser-profile/`. It uses the configured Opera GX executable when found; otherwise it uses installed Chromium. It does not attach to your personal browser, copy passwords, or read existing personal tabs.
- Managed tools can navigate, read page text, list/switch/close tabs, scroll, fill text/search fields, select dropdown options, and click observed controls. Clicks, filling, selection and closing tabs require confirmation. Re-inspection is required when a reference expires or its label changes. Filled text is not automatically submitted.
- Failed allowlisted reads can recover by choosing another query/source. Repeated failures, denied confirmations, blocked/nested tasks and uncertain side effects stop execution. GUI workflow attempts are recorded immediately in the audit log.
- Realtime loads up to 12 redacted recent text/voice turns as historical context. On session end it saves ordered user transcripts and fully played completed assistant replies. Interrupted or unheard replies are excluded. The existing memory-context setting disables voice history loading/saving; clearing memory during a live session prevents that session from restoring the cleared history. Conversation storage remains bounded to 80 turns. It is not a vector database.

Examples for voice or the CLI:

```text
managed browser https://plasico.bg
inspect browser
browser tabs
сам реши стъпките отвори https://example.com и ми кажи заглавието
спри задачата
```

Browser installation (already installed on this laptop):

```powershell
python -m pip install -e ".[browser]"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) "data\browser-binaries"
python -m playwright install chromium
```

The implementation follows the [Playwright browser-context API](https://playwright.dev/python/docs/api/class-browsertype) and [locator API](https://playwright.dev/python/docs/api/class-locator). `python tools/check_autonomy.py --opera` checks a public test page without microphone access. Add `--live-api` to run a bounded paid model-driven check. Diagnostic results/screenshots go to `data/diagnostics/`.

Limits: this is bounded, user-directed autonomy, not an unrestricted background agent. There is no automatic login, payment entry, upload, download acceptance, CAPTCHA bypass, iframe/shadow-root form automation, or guarantee that every site's controls are accessible. Reading exposes page text to the configured model when it is used in a task. HTTP(S), credential and private-address checks are defense in depth, not a hardened network sandbox against DNS rebinding or a browser exploit. Browsing uses Chromium's sandbox. Opera's internal startup tabs are not controlled. Third-party browser compatibility can change with updates.

## Voice Update (2026-09-05)

Start the current source version with `./run.ps1 --gui`. Quit an older running copy from its tray menu first. The existing installer bundle is not rebuilt by source edits.

- The central play button starts a Realtime conversation with a spoken Bulgarian greeting. The app waits for the API to accept its configuration before reporting that it is listening.
- Playback uses a separate PCM callback. Interruptions discard pending sound and truncate the unheard part of the server conversation. Input transcription drives a temporary caption; local history follows the memory setting.
- Settings > Audio > **Test speaker tone** plays a local tone. **Test voice** generates spoken Bulgarian. Playback failures appear in the window with an error message.
- Choose the audio output in Settings. Saved device names survive changes to Windows device numbering. A disconnected named speaker is reported instead of silently selecting another device.
- Classic voice waits for its spoken reply before reopening the microphone. Realtime actions pass through the GUI command queue, confirmations, and audit log.
- Quick actions and modes are available as backend voice tools, not visible main-window panels.

The Realtime protocol follows the [OpenAI conversation guide](https://developers.openai.com/api/docs/guides/realtime-conversations). To verify the API without opening a microphone, run `python tools/check_realtime_connection.py`. This makes a small paid API request and saves a greeting to `data/diagnostics/realtime-greeting.wav`.

The live configuration and generated audio were verified locally. Microphone quality, echo cancellation, and whether the selected Windows output is audible still require a listening test. Realtime now shares recent conversation history as described above. Full native-app automation, advanced browser interactions and all third-party integrations remain separate work.

## What it can do now

- Open arbitrary public HTTP(S) URLs, plus convenient aliases like Facebook, Instagram, YouTube, ChatGPT, Gmail and Google.
- Open installed apps by alias, for example Opera GX, Notepad, Calculator, Settings, Task Manager.
- Discover installed apps from the Windows Start Menu when an alias is not configured.
- Refresh and list a local installed-app launcher database.
- Load personal aliases and preferences from `data/settings.json`.
- Write command history, parsed intent, permission level, confirmation status, and errors to `logs/audit.jsonl`.
- Change, mute, or set system volume by percentage.
- Check Windows Update for pending software updates.
- Open the Windows Update settings page.
- Show NVIDIA and generic driver information from Windows WMI/CIM.
- Check pending driver updates through Windows Update.
- Enable or disable internet adapters and Bluetooth devices with confirmation.
- Open NitroSense if Windows can find it in Start apps.
- Read CPU/GPU usage, NVIDIA GPU temperature and CPU temperatures from a configured supported sensor provider; report missing sensors explicitly.
- Apply Quiet, Study, Battery Saver, and Gaming modes.
- Warn when exposed CPU/GPU thermal sensors are above a threshold.
- Open the last recent Windows file shortcut.
- Create draft `.docx` documents.
- Clean old temp files with confirmation.
- Show memory-heavy processes.
- List startup programs.
- Create folders and files inside the Jarvis workspace.
- Answer internet-backed questions through OpenAI when `OPENAI_API_KEY` is set.
- Fall back to normal AI conversation for casual text that is not a computer command.
- Add relevant saved memories as private context to casual AI conversation when they match the current message.
- Keep a short local conversation history in `data/conversation_history.jsonl` for follow-up context.
- Store, categorize, update, search, and forget user-approved long-term memories in a local SQLite database (`data/memory.sqlite3`).
- Store episodic conversation and action-history summaries in `data/episodic_memory.jsonl`, including automatic conversation summaries after enough new turns.
- Search long-term and episodic memories by meaning with a local BG/EN semantic-like matcher.
- Save and show allowlisted personal preferences such as how Jarvis should address you, preferred browser, and preferred volume.
- Answer "what did you do recently?" from the audit log.
- Show the latest developer trace with intent, action/tool, permission, confirmation, latency, and metadata.
- Attach a command session timeline to each CLI/GUI command result and audit record.
- Route ambiguous natural-language requests through an OpenAI structured intent parser that can choose only registered Jarvis tools.
- Require low-confidence or underspecified model-selected actions to ask a clarification question before any tool runs.
- Record model-selected tool traces in metadata (`llm_tool_trace`) with the selected tool, arguments, permission, status, confidence, reason, and result.
- Search the web through a browser-control backend, save numbered results, and open a chosen result in the preferred browser.
- Open or read saved browser/research results by matching text in the title or URL, for example `отвори резултата за plasico`.
- Run safe multi-step workflows with per-step results, starting with shopping deal search + open-first-result.
- Plan simple multi-step workflows through OpenAI structured output, then execute only validated registered tools.
- Preview OpenAI-planned workflows and require approval before any workflow containing important/admin steps runs.
- Route normal chat/research/tool requests through a conversation-first structured intent pass before static command rules, while keeping direct high-impact commands local and confirmation-first.
- Run explicit adaptive workflows that decide the next registered tool after seeing previous tool results.
- Extract readable text from http/https webpages and from saved web candidates.
- Research a topic on the web, read safe top sources, summarize findings, and save numbered source candidates for follow-up.
- Capture and describe the current screen with AI vision after explicit confirmation.
- Open NVIDIA driver pages.
- Restart, shutdown, or sleep the laptop only after explicit confirmation.
- Run in dry-run mode so you can see what it would do before allowing actions.
- List the registered backend tools and their permission levels.
- Listen on the microphone and respond by voice in Bulgarian or English (`--voice`).
- React only to wake phrases (`jarvis`, `hey jarvis`, `здравей jarvis`, `джарвис`), including mishearing-tolerant fuzzy matches.
- Keep a short active voice session after a wake-word command so follow-up replies can be spoken without repeating the wake word.
- Warn out loud about low battery, lost/restored internet, new Windows updates, and NVIDIA driver changes (`--monitor`).
- Run as a native voice-first desktop app with a tray icon, System Status, Readiness, an audio-reactive core, settings and a first-run wizard (`--gui`). Classic push-to-talk remains available from Settings and the global `Ctrl+Space` hotkey/overlay. Packageable into a standalone `Jarvis.exe`.

## Quick Start

```powershell
cd C:\Users\Berk\Desktop\Jarvis
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
python -m jarvis
```

For quick local runs without installing the package:

```powershell
.\run.ps1
.\run.ps1 --dry-run здравей jarvis отвори facebook
```

Try:

```text
здравей jarvis отвори facebook
jarvis отвори opera gx
jarvis отвори plasico
jarvis отвори plasico.bg
jarvis отвори plasico точка bg
jarvis отвори гейминг мишки в пласико
jarvis в кои магазини има намаления за гейминг мишки
jarvis намери оферти за гейминг мишки и отвори първия
jarvis отвори първия
jarvis прочети страницата https://example.com
jarvis прочети първия
jarvis търси в браузъра gaming mouse
jarvis потърси gaming mouse и отвори първия
jarvis провери playwright
jarvis проучи най-добрите гейминг мишки до 100 евро
jarvis сравни rtx 4060 и rtx 4070
jarvis какво има на екрана
jarvis защо ми дава тази грешка
jarvis провери screen vision
jarvis адаптивно отвори facebook и после реши дали е готово
jarvis увеличи звука
jarvis направи звука на 30
jarvis провери nvidia драйверите
jarvis провери всички драйвери
jarvis провери chipset драйверите
jarvis провери driver updates
jarvis провери температурите
jarvis предупреди ме ако температурите са над 85
jarvis отвори nitrosense
jarvis quiet mode
jarvis режим учене
jarvis режим батерия
jarvis режим игра
jarvis отвори последния файл
jarvis направи ми документ за втората световна война
jarvis почисти temp файлове
jarvis какво ми товари компютъра
jarvis провери стартъп програмите
jarvis refresh app database
jarvis list app database
jarvis покажи tools
jarvis undo
jarvis създай папка notes
jarvis създай файл notes/todo.txt
jarvis запомни това любимият ми браузър е Opera GX
jarvis какво помниш
jarvis забрави Opera GX
jarvis търси семантично в паметта любим браузър
jarvis обобщи разговора
jarvis обобщи действията от последните 10 минути
jarvis покажи епизодична памет
jarvis какво направи през последните 10 минути
jarvis покажи последния trace
jarvis покажи trace action open_url
jarvis покажи failed trace
jarvis покажи trace source gui
jarvis скучно ми е
jarvis какво мислиш за тази идея
jarvis сравни rtx 4060 и rtx 4070
jarvis провери в интернет какво е станало през втората световна война
jarvis провери windows update
jarvis отвори windows update
jarvis рестартирай лаптопа
```

## Voice Mode and Background Monitors

Voice input/output and the background monitors are optional and load their dependencies lazily, so plain text mode (including `--dry-run` and one-shot commands) never requires them to be installed.

```powershell
pip install -e .[voice]
# or: pip install -r requirements.txt

python -m jarvis --voice                  # listen on the mic, reply by voice
python -m jarvis --voice --no-tts          # listen, but print replies instead of speaking
python -m jarvis --monitor                 # spoken/console alerts, typed commands
python -m jarvis --voice --monitor         # both together
python -m jarvis --list-voices             # show installed text-to-speech voices
python -m jarvis --list-openai-voices      # show built-in OpenAI text-to-speech voices
python -m jarvis --list-audio-devices      # show speaker/headset outputs Jarvis can use
python -m jarvis --voice-doctor            # diagnose mic, speaker, OpenAI TTS, Realtime, output device
python -m jarvis --test-output-tone        # play a short tone through the selected output device
python -m jarvis --test-speaker            # speak a short Bulgarian test phrase
python -m jarvis --audio-output-device 17 --test-speaker
python -m jarvis --set-audio-output-device 17
python -m jarvis --realtime-voice          # check OpenAI Realtime voice readiness/config
```

For a more natural Jarvis-like voice, set `tts_provider` to `openai` in `data/settings.json` or use `$env:JARVIS_TTS_PROVIDER="openai"`. OpenAI TTS does not require `pyttsx3` when `OPENAI_API_KEY` is available; Windows voices are only needed as the offline/fallback provider.

`--realtime-voice` is the next voice layer: an OpenAI Realtime voice-agent session using `gpt-realtime-2.1`, 24 kHz PCM audio, semantic VAD, and a built-in voice such as `cedar`/`marin`. It first reports whether `OPENAI_API_KEY`, `websockets`, and `sounddevice` are available. If they are, it starts a live microphone -> Realtime websocket -> speaker loop and routes Realtime function calls back through the same Jarvis tool registry and confirmation gates used by the CLI/GUI.

Say a wake phrase and the command in one breath ("hey jarvis отвори facebook"), or say the wake phrase alone and Jarvis will prompt and listen again for the command. After Jarvis successfully answers, short follow-up replies are accepted for about 20 seconds without repeating the wake phrase, so you can continue naturally. Say `спри да слушаш`, `край jarvis`, or `stop listening` to end that active voice session early. Outside that short active window, utterances that do not start with a wake phrase are ignored, so ambient conversation is not treated as a command.

Say `отказ`, `забрави`, `never mind`, or `cancel` after the wake word to abort a command you started saying instead of Jarvis trying (and failing) to route it — Jarvis replies "Добре, отказано." / "OK, cancelled." and waits for the next command. If what Jarvis heard after the wake word is empty or only a word or two (almost always a clipped mishear, not a real command), it says "Не те чух добре. Опитай пак." / "I did not hear that clearly. Please try again." instead of sending noise to the router as an unknown command.

Destructive commands (restart/shutdown/sleep/etc.) still require typing `YES` in the terminal exactly as in text mode — voice never bypasses `SafetyPolicy`. Jarvis announces "check the terminal" out loud before that prompt blocks.

Background monitors run on independent timers per check (battery every 5 min, internet every 30s, NVIDIA driver hourly, Windows Update every 6 hours, CPU/memory every 2s, GPU every 5s, disk every 5 min) so a slow check never delays the others. Monitor state is in-memory only and resets each run. The GPU check also warns once when temperature reaches the Settings > "Temperature warning threshold" value (85°C by default, matching `jarvis предупреди ме ако температурите са над 85`) and re-arms once it drops back below that value, so it will not repeat every 5 seconds while sustained.

Known limitations:

- Voice input uses the free Google Web Speech API (via `SpeechRecognition`) — it needs internet access and has no official uptime/quota guarantee. There is no offline wake-word engine (like Porcupine) wired in; the wake phrase is matched against each recognized phrase instead, so idle listening periodically calls the cloud API rather than running a local always-on detector.
- Realtime voice is the primary GUI voice mode when `OPENAI_API_KEY`, `websockets`, and `sounddevice` are available. The central play button opens the microphone, streams speech to OpenAI Realtime, and plays spoken replies back. Classic `--voice` / Settings > Audio > **Classic voice fallback** uses phrase recording -> STT -> router -> TTS rather than a permanent bidirectional audio stream.
- Windows text-to-speech uses `pyttsx3` (Windows SAPI5). A Bulgarian voice must be installed (Settings > Time & Language > Speech > Add voices) for Bulgarian replies to sound right; otherwise Windows fallback voices will mispronounce Bulgarian text. OpenAI TTS is the better option for a more natural assistant voice when your API key is configured.
- Command results from the router are currently English text, so spoken replies use an English voice even when you spoke Bulgarian. Bulgarian spoken replies will follow once the router returns localized messages.
- `PyAudio` (required by `SpeechRecognition` for microphone access) can fail to build from source on Windows. If `pip install -e .[voice]` fails on it, try `pip install pipwin && pipwin install pyaudio`, or install a prebuilt wheel matching your Python version.

## Native Desktop App

A PySide6 tray app with voice built in — the intended day-to-day way to run Jarvis, alongside the text CLI above.

```powershell
pip install -e .[gui]
# or: pip install -r requirements.txt

python -m jarvis --gui
# or directly:
python -m jarvis.gui
```

- **Tray icon** with 5 states (idle / listening / processing / unclear / warning) and native Windows toast notifications for temperature warnings, Windows Update availability, low battery, low disk space, and connectivity changes. Closing the window hides it to the tray; use the tray menu's Quit to actually exit. The tray menu can also re-open the first-run setup wizard at any time.
- **Main window**: an unframed native voice core, System Status and Readiness. There are no conversation, task, quick-action, mode or tool tabs. Speak commands during the Realtime call; backend tools, memory and audit records remain available.
- **Settings dialog**: website/app aliases, safety preferences, browser/path, mode profiles, temperature threshold, voice providers, live model/voice, output device, memory context and startup/hotkey settings. Live changes apply on the next call; classic STT/TTS provider changes need a restart. Monitoring and action preferences are read by their existing backends.
- **Voice**: the central play/stop icon starts and ends Realtime. The pause icon mutes input without ending the call; the separate cancel icon stops pending actions. No wake phrase is needed while connected. Classic fallback and push-to-talk are explicitly available under Settings > Audio. They share the microphone lock with Realtime and never run as a hidden startup listener.
- **Voice Doctor / Test Voice**: Settings > Audio contains diagnostics, a spoken test and a local tone. If Jarvis can hear you but you cannot hear it, choose the exact headset/speaker in Settings > Voice > Audio output device, or test candidates from the CLI with `python -m jarvis --audio-output-device 17 --test-speaker` before saving one with `--set-audio-output-device 17`.
- **Overlay + global hotkey**: `Ctrl+Space` (system-wide — works even when Jarvis isn't the focused window) toggles a small always-on-top overlay showing the current mic state, and triggers push-to-talk in the same press. Skipped automatically if the combination is already bound by another application; Jarvis notifies once and keeps running rather than failing to start. Can be turned off entirely from Settings if it conflicts with another application's shortcut.
- **First-run setup wizard**: walks through OpenAI API key status (read-only — it never takes or stores a pasted key, only shows a `setx` command to copy), a microphone check, a speaker/voice test, the wake phrases, filesystem write permissions, and preferred browser. Runs automatically before the first launch, whenever `data/settings.json` doesn't exist yet, and is re-runnable any time from the tray menu.
- **Confirmation dialogs**: disruptive commands (restart/shutdown/sleep/internet/Bluetooth/temp cleanup/gaming mode) show an on-screen Yes/No dialog instead of a terminal prompt. Every GUI action still goes through the same permission/confirmation gate.

Turning this into a standalone `Jarvis.exe` that does not need Python installed is covered in [Packaging](#packaging-standalone-exe) below.

See [`NITROSENSE_FINDINGS.md`](NITROSENSE_FINDINGS.md) for the NitroSense integration research: a real WMI provider exists (`AcerGamingFunction`/`AcerGenericMethod` in the `root\WMI` namespace) but uses an undocumented, opaque calling convention, so Jarvis only ever probes for its *presence* — it never calls into it or guesses at the protocol. Temperature/fan monitoring stays on the documented `nvidia-smi`/thermal-zone paths; "open NitroSense" remains how you reach fan curves, RGB, and profile switching.

## Packaging (standalone .exe)

```powershell
pip install -e .[installer]
pyinstaller installer/jarvis.spec --noconfirm --distpath installer/dist --workpath installer/build
```

Produces `installer/dist/Jarvis/Jarvis.exe` plus an `_internal/` folder of dependencies (~185 MB total, mostly Qt) — kept under `installer/` rather than the repo root so build output stays next to the spec that produced it. `--distpath`/`--workpath` are optional; omit them to get PyInstaller's normal `dist/`/`build/` at the repo root instead. Either way this is a `--onedir` build, not `--onefile`, since a one-file build self-extracts to a fresh temp directory on every launch, which is bad startup latency for something meant to auto-start at login. Built and smoke-tested on this machine (real `pip install pyinstaller`, real build, real launch — the tray icon appeared and the process ran cleanly with no crash). Not yet code-signed, so Windows SmartScreen/antivirus may flag an unrecognized publisher on first run; that is a known, unsolved gap, not something worked around here.

Notes for anyone touching the packaging setup:

- [`installer/entrypoint.py`](installer/entrypoint.py), not `src/jarvis/gui/__main__.py`, is the actual PyInstaller entry point. PyInstaller's `Analysis()` loads the target script with no package context (the same as double-clicking a `.py` file), so `__main__.py`'s relative import (`from .app import main`) silently fails to resolve during static analysis — the build "succeeds" but only bundles the standard library, which is exactly what happened the first time this was built. The entry point needs an absolute import (`from jarvis.gui.app import main`) instead; everything imported after that point is a normal package import, and relative imports inside those modules work fine.
- `gui/app.py` sets `comtypes.client.gen_dir = None` at import time. `comtypes` (used by pycaw's volume control and pyttsx3's SAPI5 driver) disk-caches generated COM wrapper modules on first use by default, and that cache directory is not reliably writable inside a frozen bundle — this forces in-memory generation instead.
- `python-docx`'s bundled `docx/templates/default.docx` (needed by "make me a document about...") and pyttsx3's platform driver module are pulled in automatically by `pyinstaller-hooks-contrib`'s `hook-docx.py` / `hook-pyttsx3.py` — installed as a PyInstaller dependency, not something this repo vendors. Verify both actually land in `dist/Jarvis/_internal/` after a build rather than assuming it; an older `pyinstaller-hooks-contrib` on some other machine could regress this silently.
- Screen vision (`Pillow`) and browser automation (`playwright`) are not bundled — they are optional extras this build does not install, and both already fail gracefully (`try`/`except ImportError`) when absent, same as running unpackaged without them.

Autostart (Settings > "Start Jarvis when Windows starts") works the same way against a packaged exe as it does in development: `gui/autostart.py` detects `sys.frozen` and points the Startup-folder shortcut straight at `Jarvis.exe` instead of `pythonw.exe -m jarvis --gui`.

## Running Tests

```powershell
pip install -e .[dev]
pytest
```

Tests run against `src/` directly (no install required) via `pythonpath` in `pyproject.toml`. Coverage includes Bulgarian command routing (including the confirmation flow for destructive commands), wake-word matching, language detection, the speech-to-text language-fallback logic, and the background monitor alert policy — all without touching a real microphone, speaker, or network.

GUI tests (`pip install -e .[gui]` first) run headless via Qt's `offscreen` platform plugin, set automatically in `tests/conftest.py` — no real display needed. One gotcha if you add more: `QTest.keyClicks()` (synthesized key-press events) hangs indefinitely on non-ASCII text under `offscreen`, since it tries to map each character to a virtual keycode via a keyboard layout that doesn't have Cyrillic in it. Use `widget.setText(...)` for Cyrillic input in tests instead; `QTest.keyClick()` for single control keys like Enter is unaffected.

## Integration Roadmap

- System controls: battery plans, brightness, night light, focus assist.
- Health checks: Windows Update, NVIDIA driver version, disk space, battery health, startup apps.
- Modes: Quiet, Gaming, Study, Battery Saver.
- Apps: configurable aliases for games, browsers, Discord, Steam, Spotify, Office, IDEs.
- Websites: configurable shortcuts for social media, mail, school/work portals.
- Automation: reminders, scheduled checks, warnings when updates or drivers are available.
- Keep expanding preferences into real behavior: `preferred_browser`, mode volumes, temperature threshold, and Gaming close/launch app lists are live; next useful additions are brightness profiles, focus assist rules, and app-specific audio profiles.

## OpenAI Setup

Jarvis uses the OpenAI Responses API for internet-backed questions. Set your API key before using AI answers:

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

The default model is `gpt-5.6-sol`. It is configured in `data/settings.json`:

```json
"openai": {
  "model": "gpt-5.6-sol",
  "speech_to_text_provider": "openai",
  "speech_to_text_model": "gpt-transcribe",
  "tts_provider": "openai",
  "text_to_speech_model": "gpt-4o-mini-tts",
  "text_to_speech_voice": "cedar",
  "text_to_speech_instructions": "Speak like a calm, concise, intelligent desktop assistant."
}
```

You can override it temporarily:

```powershell
$env:JARVIS_OPENAI_MODEL="gpt-5.6-terra"
```

Structured intent, workflow planning, and casual conversation use OpenAI only when `OPENAI_API_KEY` is available. Deterministic local commands still run first, so high-impact actions cannot be smuggled through model output; planned workflows execute through the same registered tool and confirmation layers as typed commands. For casual chat, Jarvis may include locally matched memory snippets in the prompt so it can answer more personally without requiring a separate memory command.

The structured intent parser returns `confidence` and `clarification_question`. If the model-selected tool action is low confidence or underspecified, Jarvis returns a clarification request (`intent=llm.clarification`, `action=ask_clarification`) and does not execute the tool. Admin/confirmation-level tools require higher confidence than safe tools. A pending yes/no clarification is one-turn only: reply `да` / `yes` to run the saved tool through the normal safety gates, or `не` / `отмени` / `cancel` to discard it.

If a model-selected tool is missing a required argument, Jarvis asks for that value (`intent=llm.argument_clarification`, `action=ask_tool_argument`). Blank or null required values count as missing. Your next reply is used as the missing value and then the tool runs through normal validation and confirmation. Unexpected model arguments are rejected before execution.

When OpenAI responses expose usage information, Jarvis stores it in command metadata under `ai_trace`, `intent_parser_metadata["ai_trace"]`, or `workflow_planner_metadata["ai_trace"]`. The trace includes the provider, model, operation, response id when available, token usage, and tools such as `web_search`.

## Memory

Jarvis uses three local memory layers:

- Short conversation history: `data/conversation_history.jsonl`, used for immediate follow-up context.
- Long-term facts: `data/memory.sqlite3`, created only when you say commands like `jarvis запомни това ...`.
- Episodic memory: `data/episodic_memory.jsonl`, short summaries of what you discussed or worked on.
- Semantic memory search: local ranking across long-term and episodic memory with Bulgarian/English aliases like `браузър`/`browser`, `екран`/`screen`, and `действия`/`actions`.

Useful commands:

```text
jarvis запомни това любимият ми браузър е Opera GX
jarvis запомни като preference любимият ми браузър е Opera GX
jarvis какво помниш
jarvis промени памет 1 на любимият ми браузър е Opera GX
jarvis сложи памет 1 в категория website
jarvis покажи категории памет
jarvis търси семантично в паметта любим браузър
jarvis намери в паметта екран browser
jarvis обобщи разговора
jarvis обобщи действията от последните 10 минути
jarvis покажи епизодична памет
jarvis какво помниш от разговорите browser
jarvis наричай ме берк
jarvis любимият ми браузър е opera gx
jarvis предпочитан звук 30
jarvis сложи предпочитания звук
jarvis покажи предпочитания
```

Long-term memory categories are: `general`, `preference`, `project`, `device`, `game`, `website`, and `routine`. Bulgarian aliases like `предпочитания`, `игри`, `сайтове`, and `рутини` are normalized to those categories.

Episodic summaries can come from conversations (`source=conversation`) or recent audit/action history (`source=actions`). Conversation summaries are created automatically after enough new successful conversation turns in normal mode. In `--dry-run`, Jarvis does not write automatic conversation summaries.

Casual AI conversation also receives up to a few relevant semantic memory matches and relevant saved settings preferences as private context. This is meant for questions like `jarvis помниш ли любим браузър`; explicit computer actions still go through the normal tool and permission system.

Long-term memory writes, short conversation history, command sessions, tool argument metadata, and audit/developer traces apply first-pass secret redaction for obvious API keys, access tokens, bearer tokens, and password assignments. Redacted results use `[REDACTED_SECRET]` and include `privacy_redacted` / `privacy_findings` metadata on memory commands. This is a guardrail, not a secure secrets vault; real keys should stay in environment variables or a proper credential store.

You can disable memory context for casual chat by setting this in `data/settings.json`:

```json
"openai": {
  "use_memory_context": false
}
```

## Browser Automation

Jarvis currently has safe browser-control primitives:

- `browser_search`: search and save numbered results.
- `browser_open_result`: open a saved result.
- `browser_open_matching_result`: open a saved result by matching text in the title or URL.
- `browser_search_and_open`: search and open a selected numbered result.
- `browser_open_search_page`: open a Google results page.
- `show_browser_session`: show the current saved search/browser context.
- `compare_browser_session_pages`: compare pages already read in the current browser session, using OpenAI when configured and a local excerpt fallback otherwise.
- `answer_browser_session_question`: answer a follow-up question from pages already read in the current browser session.
- `browser_automation_status`: check whether optional Playwright support is installed.

To install the optional Playwright Python package:

```powershell
pip install -e .[browser]
python -m playwright install chromium
```

Saved browser/research candidates can be continued by number (`отвори първия`, `прочети втория`) or by matching text (`отвори резултата за plasico`, `прочети резултата за nvidia`). Jarvis also keeps a lightweight local browser session with the latest saved results, opened results, and read page excerpts, so follow-ups like `какво прочете`, `сравни тези резултати`, and `какво казват страниците за батерията` work after reading pages. Session answers/comparisons can use OpenAI for concise synthesis when configured; otherwise Jarvis falls back to local excerpt notes. In both paths, saved webpage text is treated as untrusted evidence only. Opera GX opening works through the preferred-browser launcher. Full control of an existing Opera GX window requires launching it with a remote-debugging port or using a separate automated browser session; Jarvis does not yet click arbitrary UI controls, submit purchases, bypass logins, or interact with security-sensitive pages.

## Screen Vision

Jarvis can capture the current screen and ask the configured AI model to describe it:

```powershell
pip install -e .[vision]

jarvis какво има на екрана
jarvis защо ми дава тази грешка
jarvis провери screen vision
```

Screen vision is `confirm` level because screenshots may contain private data. The captured image path is stored in command metadata as `screenshot_path`, and results are marked `privacy_sensitive`.

When a planned workflow includes important/admin steps, Jarvis shows the plan first and requires approval before running it. Workflow and adaptive workflow plans are rejected before preview/execution if a step has missing, blank, null, or unexpected tool arguments. The workflow metadata includes `workflow_preview`, `workflow_requires_approval`, `workflow_highest_permission`, `workflow_risky_tools`, `workflow_step_count`, and the executed `workflow_steps` timeline for the GUI/developer panels. Each executed step includes tool arguments, latency, status, message, attempt count, and `result_metadata` from the underlying tool. Failed workflow steps also include `workflow_recovery` metadata with the failed tool, category, attempts, retry state, and a recommended next action. Planned and adaptive workflows may retry allowlisted safe information-gathering tools once, but confirmation/admin actions are never retried automatically.

Every command executed through the CLI or GUI now also includes session metadata:

- `session_id`: unique id for that command run.
- `state_timeline`: ordered state events such as `received`, `thinking`, `executing`, `waiting_confirmation`, `confirmation_resolved`, `completed`, or `failed`.

The same metadata is written to `logs/audit.jsonl`, so the GUI can show a real execution timeline instead of guessing from final messages.

Failed command results are enriched with first-pass error taxonomy metadata before they reach the CLI/GUI audit layer:

- `error_type`: compact category such as `blocked_action`, `missing_argument`, `configuration_missing`, `not_found`, or `transient_external_failure`
- `error_severity`: `info`, `low`, `medium`, or `high`
- `recommended_action`: machine-readable next step for GUI/developer views
- `retryable`: whether an automatic retry may be reasonable

Adaptive workflow mode is intentionally explicit. Start with `jarvis адаптивно ...`, `jarvis agent mode ...`, or `jarvis сам реши стъпките ...`. In that mode Jarvis asks the model for one next step at a time, after each previous tool result, but every step is still validated against the registered tool list and confirmation policy. Adaptive metadata includes `adaptive_workflow`, `adaptive_goal`, `adaptive_decisions`, and `workflow_steps`.

For single model-selected tool calls, `llm_tool_trace` records whether the model-selected tool was executed, cancelled, rejected as unregistered, stopped for clarification, stopped for missing/unexpected arguments, or cancelled after clarification. This is the audit trail that proves the model did not run arbitrary shell commands.

OpenAI-backed operations may also include `ai_trace` metadata:

- `provider`, `model`, `operation`
- `response_id` when the SDK returns one
- `usage.input_tokens`, `usage.output_tokens`, `usage.total_tokens` when available
- `tools`, for calls such as web-backed answers

Developer traces can be filtered through the router or the `filtered_developer_traces` tool. Supported filters are `action`/`tool`, `intent`, `source`, `permission`, `ok`/failed status, `error_type`, `recommended_action`, recent minutes, and limit. Results include `trace_filter`, `trace_filter_count`, and a compact `traces` list for GUI tables. Router shortcuts such as `jarvis покажи blocked errors` map to the corresponding error taxonomy filter.

In `--dry-run`, adaptive mode does not call OpenAI; it reports what it would run.

Webpage extraction and research are intentionally conservative: they only read `http`/`https` pages, reject localhost/private-network URLs unless a future allowlist is added, strip script/style content, limit downloaded bytes, and mark extracted text as `untrusted_web_content` in metadata. Website/PDF/email text must never be allowed to override Jarvis safety rules. Research and web-backed AI prompts use a shared prompt-injection guard with explicit untrusted-content boundaries; related results include `content_trust=untrusted`, `prompt_injection_guard=true`, and `prompt_guard_policy=web_content_boundaries`. Research sources also include first-pass `quality_score`, `quality_label`, `quality_reasons`, an aggregate `source_quality` summary, and `source_coverage` with coverage/conflict markers, so Jarvis can hedge when excerpts are thin, sources look weak, or obvious source conflicts appear. Research results are saved as numbered candidates, so follow-up commands like `отвори първия` and `прочети втория` work after a research command.

## Safety Model

Jarvis is allowed to perform local Windows actions, but destructive or disruptive commands require confirmation. This includes restart, shutdown, sleep, disabling network adapters, and similar actions.

Kernel-level access is intentionally not part of the first version. The safe route is to use supported Windows APIs, PowerShell cmdlets, WMI/CIM, Settings URI handlers, and vendor tools.

Permission levels are attached to each command result:

- `safe`: read-only or low-risk actions like opening a website or checking temperatures.
- `confirm`: disruptive actions that need explicit confirmation, like temp cleanup or gaming mode.
- `admin`: actions that may require administrator rights, like network/Bluetooth changes, driver checks, or power settings.
- `blocked`: kernel-level or security-sensitive requests that need a separate approved design.

Some actions are reversible. Use `jarvis undo` or `jarvis върни последното` to undo the last rollback-supported action after confirmation.

## Working With Claude Code

Open Claude Code in this same folder:

```powershell
cd C:\Users\Berk\Desktop\Jarvis
claude
```

Claude Code should read `CLAUDE.md`. Codex should read `AGENTS.md`. Both files describe the same project direction so the assistants can work in the same workspace without stepping on each other.

For the current split of work, read `TASK_SPLIT.md`.
