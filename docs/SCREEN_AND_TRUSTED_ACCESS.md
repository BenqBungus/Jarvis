# Screen assistance, document OCR and trusted local actions

## Screen assistance

The main monitor button now opens the separate GPT-5.6 Sol Screen Chat; see
SCREEN_CHAT.md. For the existing Realtime visual feed, use Settings > Audio >
Start or stop Realtime screen sharing, or say `Start screen sharing`.
Approve the disclosure and keep the visible Stop banner
on screen. Then ask `Ask screen why does this code fail?` and, after making a
change, `Ask screen did I fix it?` Natural-language voice can call the same tool.

There is no countdown or five-minute expiry. Sharing remains enabled until Stop,
application shutdown, capture failure or loss of the visible privacy indicator.
During an active Realtime voice call, a new primary-screen image is captured about
every two seconds and sent automatically when it changes, without another question.
Only two recent image items are retained in the Realtime conversation; older image
items are deleted. No response is requested merely because an image arrived.
This may increase API usage. Frames are not saved as local image files or voice
memory entries. Stop clears local screen context and requests removal of streamed
image items; already-sent data cannot be recalled or guaranteed erased by the API.

The banner says LIVE when frames are being supplied to Realtime, or START VOICE
when waiting for a call. Without Realtime, explicit screen questions still capture
a fresh image and use short question/answer context. Those separate Responses API
requests use store=false; that is not a zero-retention guarantee. Spoken screen
answers may remain in ordinary conversation history. Close private windows first.

This is not Copilot integration, Discord frame-rate video, or automatic clicking.
It explains visible content and suggests steps. Small text, cropped windows,
unseen files and changing screens can limit accuracy. It must not claim to have
edited or tested code just from looking at a screenshot.

## Full access for local files and apps

Settings > Safety confirmations > `Full access: trusted local files and apps`.
Save and accept the one-time warning. This is OFF by default and is never
enabled by a spoken tool call. Turning it off and saving restores prompts.

This preauthorizes requested folder/file creation, copying, moving, renaming,
ZIP operations, recycling, closing/end-process tools and saving reviewed edit
copies. Ending an app may lose unsaved work. An ambiguous target still needs
clarification; a short-lived observed process selection is still required.

`Close folder` or `Close folder Downloads` closes one observed File Explorer
window, including its tabs, with a normal close request. It does not delete the
folder or terminate explorer.exe. With several windows and none in the foreground,
specify the exact window title. Native Windows dialogs are never dismissed for you.

Example: `Create folder Documents/Test`, then
`Delete folder Documents/Test`. Delete means Windows Recycle Bin, never a
permanent-delete fallback. Restore from Windows Recycle Bin, not Jarvis Undo
Center. A bounded directory scan rejects private/system paths, links, protected
roots and oversized trees. System/security processes remain blocked. This is
not a hostile multi-user filesystem sandbox.

Administrative/network actions and starting screen/document cloud analysis
still require their existing approvals. Full access does not grant Windows
administrator rights. Audit confirmation indicates policy approval, which can
be preauthorization rather than an individual dialog in this mode.

## PDF and Word

`Analyze document "C:\Users\YourName\Downloads\Sample.pdf"`

`Ask document summarize the argument and challenge its weak points`

`Write document "My report" to "C:\Users\YourName\Documents\Report.docx" about a critical review of this document`

PDF embedded text and DOCX body paragraphs/tables are read locally. Windows OCR
is attempted on image-only PDF pages and supported embedded Word images. OCR
does not interpret charts or guarantee exact quotations. Maximum: eight OCR
images, 120 PDF pages, 60000 extracted characters, 20 MiB input and the existing
20-second worker deadline. Large scans may time out or be partial: split them
into smaller documents. DOCX image labels are archive order, not page numbers;
headers, footnotes, text boxes and other non-body material remain incomplete.
Legacy .doc, encrypted files and macros are not supported.

OCR needs a supported Windows OCR language installed. It runs locally; subsequent
AI summary/discussion sends extracted text to OpenAI after approval. Do not use
confidential work documents without the necessary permission. Original documents
are not edited by analysis or drafting.

## Test status

Unit tests use mocked cloud responses. Local Windows OCR has been exercised on
generated image-only PDF and embedded-image DOCX fixtures. Native settings tests
use Qt offscreen. These do not establish microphone quality, live cloud answer
quality, or compatibility on another Windows machine.
