# Gmail for Jarvis (first read-only version)

## Scope

Connect one Gmail account on this Windows login. Search inbox/unread messages,
read a numbered email, or send its extracted text to OpenAI for a summary.
No email sending, replies, drafts, deletion, label changes, attachment downloads,
background polling or marking messages read. Gmail access is independent of your
OpenAI API key and of the Gmail plugin in Codex/ChatGPT.

## One-time setup

1. In Google Cloud, create/select your project and enable Gmail API.
2. Configure Google Auth Platform branding and audience. For a personal Gmail
   account use External, keep the app in Testing and add your own Gmail account
   as a test user. Add the gmail.readonly scope under Data Access.
3. Create an OAuth client with application type Desktop app. Download its JSON.
   Keep it locally; do not paste it, your password or OAuth tokens into chat.
4. In the Jarvis project terminal install the OPTIONAL Google dependencies:

   ```powershell
   .\.venv\Scripts\python.exe -m pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib pywin32
   .\run.ps1 --gui
   ```

5. Open Settings > Gmail > Connect Google account. Select the downloaded JSON,
   choose your account in Google's browser sign-in and approve read-only access.
   The local callback listens on 127.0.0.1, on a temporary port, for up to two
   minutes. There is no permanent service or LAN listener.
6. An external app in Testing may need reauthorization after seven days. Public
   distribution requires a separate Google OAuth publishing/verification review;
   do not distribute your personal authorization with the application.

The Google packages are not installed automatically and have not been added to
the shared release build while Claude is editing it. The current ZIP does not
include this integration. Use the source checkout for testing.

## Commands (English and Bulgarian)

- `gmail status` / `статус на gmail`
- `check gmail` / `провери пощата`
- `unread emails` / `непрочетени имейли`
- `search gmail from:person@example.com newer_than:7d`
- `търси в gmail subject:фактура`
- `read email 1` / `прочети имейл 1`
- `read the first email` / `прочети първия имейл`
- `summarize email 1` / `обобщи имейл 1`
- `analyze email 1` / `анализирай имейл 1`
- After reading: `What should I do about this email?` / `Какво да направя с този имейл?`
- `disconnect gmail` / `изключи gmail`

Results are numbered and selections expire after 10 minutes, on a new search,
account connection change or app restart. Use an explicit number; voice intent
parsing also receives Gmail tool schemas, but is not a substitute for testing
real speech. Local/offline-only commands do not gain Gmail access.

Business analysis is separate from a short summary. It requests: sender's claims,
business relevance, priority with reasons, explicit deadlines, recommended next
steps, risks and missing context, and a reply approach. No acceptance, reply,
payment or other commitment is made. Sender authenticity and attachments are not
verified; important requests must be checked independently. Follow-up "this
email" only refers to the last email actually read in the current search, never
an assumed first result. A fresh search resets that reference.

Classic desktop and CLI voice receive readable email text instead of JSON/boundary
markers. AI tool results retain untrusted-content boundaries. Partial readings
carry a warning; they are not represented as the full message or thread. Live
voice uses its existing audio output and Gmail tools. Real playback is untested.

## Privacy and limits

- Windows Credential Manager stores the read-only refresh credential for this
  Windows user, under Jarvis/Gmail/ReadOnly. No plaintext token.json is written.
- Disconnect removes the local credential. To revoke Google's grant as well,
  remove Jarvis under Google Account > Security > Third-party connections.
- Search/reading require Jarvis confirmation. In Live mode email headers/text
  become tool results sent to OpenAI. Summaries explicitly send extracted text
  to OpenAI. Do not approve this for mail you do not want shared with the provider.
- Gmail tool results are omitted from Jarvis audit content and ordinary router
  conversation-memory writes. The audit retains action/success/confirmation.
  This is not a guarantee against all retention: voice transcripts, provider
  records, screenshots, explicit memory requests and later discussion can still
  contain information about emails. Do not read sensitive messages while screen
  sharing. A separate Claude review of voice-transcript retention is requested.
- HTML is converted to text locally without loading images or links. Attachments
  and forwarded message parts are omitted; long/unsupported messages are marked
  partial. Email instructions cannot authorize actions. Summary calls have no
  tools; check important dates or requests against the original message.
- Dry-run does not read credentials, launch OAuth, read email or call summary AI.

## Verification checklist

With your own account, manually test: connect; cancel sign-in; unread search;
empty search; read result 1; summarize after confirmation; reject confirmation;
change language; expired selection; disconnect then search; offline error.
For a suspicious email containing "ignore previous instructions", Jarvis must
summarize it as email content, never follow it or open its links automatically.
No real Gmail account or paid API request was used in automated tests.

Automated checkpoint: 273 focused tests passed, including Gmail auth/service,
confirmation rejection, private audit filtering, English/Bulgarian routing,
AI summary policy and the native connection dialog. The Google SDK/OAuth and
Credential Manager calls were mocked; real end-to-end account acceptance remains
pending setup. Google client libraries were not installed at that checkpoint.

Local setup checkpoint (2026-09-17): the optional Google libraries are now installed
in this checkout's `.venv`. `pip check` reports no broken requirements, the real
OAuth imports and bundled Gmail v1 discovery definition load successfully, and
64 Gmail-focused tests pass. These tests do not authorize or read a real account.
Google Cloud Desktop OAuth setup, user consent and live mailbox acceptance are
still pending. This local installation does not update the standalone ZIP or
install dependencies for other users.

## Official references

- https://developers.google.com/workspace/gmail/api/quickstart/python
- https://developers.google.com/identity/protocols/oauth2/native-app
- https://developers.google.com/identity/protocols/oauth2
- https://developers.google.com/workspace/gmail/api/auth/scopes
- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list
- https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get
