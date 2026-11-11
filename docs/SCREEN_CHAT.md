# Screen Chat with GPT-5.6 Sol

The monitor icon in the main window opens a separate native Screen Chat dialog.
Click Share screen and accept the one-time disclosure for that sharing session.
Type a question and press Enter or Send. Each question captures the primary screen
and sends that image, the previous successful image and up to three recent answer
pairs to gpt-5.6-sol. The model is fixed for this dialog, independently of general
chat and Realtime settings. API key, billing and access to this model are required.

Jarvis's main window and the chat briefly hide during capture, then reappear while
the model answers. Other applications are not moved or closed. The screen indicator
stays visible. This is still question-triggered image analysis, NOT continuous video.
It cannot reconstruct clicks or changes between questions.

The chat model has no command router, executor, web search or file-writing
tool. By default it has no tools. Selecting a project enables the three read-only
tools described below; optional patch proposals add a preview-only tool. Actual
writes require the separate desktop review action. Action-shaped chat text alone cannot change files. Suggestions
and code are displayed as plain text. No system action is executed from this chat.
Other explicitly requested Jarvis actions remain separate; this is not a global
read-only switch for the entire application.

Stop, closing the dialog or Escape ends sharing and discards the result of any
pending answer. An already-sent API request cannot be recalled. Clear also removes
the visible discussion and project grant. Closing/Escape also clears the discussion
and revokes project access. Reopening does not restart sharing. Retry appears as an
icon after an error and explicitly captures a new image; no automatic paid retries.

Discussion and images are held in memory, not written to conversation history or
image files. Requests use store=false, not a guarantee of zero provider retention.
Screenshot contents are untrusted input. Close confidential windows before sharing.

Realtime voice is unchanged. Its previous screen-sharing control remains in
Settings > Audio > Start or stop Realtime screen sharing and via voice commands.
Starting Screen Chat sharing stops that previous visual feed so the same screen
is not automatically streamed into the voice session too. This chat is text-only.

Offline tests cover model selection, no-tool requests, fresh images, context,
consent, Stop/Escape, stale answers, capture failures and explicit retry. Packaged
rendering is tested at 680x650 and 440x400. Actual model replies and personal-screen
capture need an opt-in test with a configured account.

## Project Diagnosis

The folder icon opens a native directory picker. Select a specific project and
accept the separate disclosure to allow its paths and selected source excerpts to
be sent to OpenAI. Then Share screen and ask, for example:

"Inspect the project and find the source of the error on screen. Cite file lines."

The model can choose list_project_files, search_project_files and read_project_file.
Search supports partial/literal names, literal content, extension, byte-size bounds
and ISO UTC modification dates. Source reads include line numbers and pagination.
Supported types include Python, JS/TS/JSX/TSX, HTML/CSS/SCSS, Java, C/C++, C#, Go,
Rust, SQL, XML, JSON, YAML, TOML, Markdown, plain text, CSV and logs.

Only the selected project is eligible. No drive-wide scan, shell execution, writes,
uploads to arbitrary destinations or background index is added. Hidden/private
paths (including config/settings), recognized credentials, linked files/folders,
system directories and common generated directories are excluded. This filtering
is conservative and is not a perfect secret detector or an OS sandbox. Choose a
non-sensitive development copy when possible. A missing search result is not proof
that a file does not exist. Semantic search is not implemented by these tools.

Each question is bounded to six model requests, twelve local tool calls, 1500
visited directory entries, 256 KiB per source file and 2 MiB total source reads.
The deadline is checked between requests and local operations (180 seconds);
already-running HTTP calls retain their own timeout. Search results and source
excerpts have additional output limits. No automatic paid retry runs.

The history icon shows tool names, relative read paths, timestamps, success/failure
and limit status. It is an in-memory operational report, not model reasoning or a
permanent transcript of file contents. Stop prevents further reads/model requests
and discards the pending answer. Clear, Remove and closing the dialog also revoke
the folder grant. Changing projects clears old image/discussion context. Tool
results are untrusted evidence and cannot grant new filesystem permissions.

Optional reviewed coding is now available in the project changes dialog. Enable
AI patch proposals to add one preview-only tool. Applying a reviewed multi-file
patch, undoing it and running pytest require separate desktop actions/approvals.
The model cannot apply or execute directly. See PROJECT_CODING.md for the workflow,
backup and execution boundaries. The separate file-edit/save-copy workflow remains
unchanged. Unattended diagnose/repair/test execution is not implemented.
