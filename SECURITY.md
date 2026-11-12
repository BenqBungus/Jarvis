# Security and local data

Jarvis is experimental desktop-assistant software. A clean secret scan is not a
guarantee that every feature is secure or that every generated action is correct.
Review permissions and confirmation prompts before using it on important files.

## Credentials

- Use Jarvis's credential settings or local environment variables. Never put real
  API keys, passwords, OAuth client secrets or access/refresh tokens in source code,
  test fixtures, screenshots, issues, pull requests or example configuration.
- Local settings, conversations, account tokens, audit logs, build outputs and
  generated reports are excluded by `.gitignore`. Do not force-add them.
- Each user must configure their own credentials. None are bundled with the source.
- If a real credential is exposed anywhere, revoke/rotate it at its provider first.
  Deleting a file or adding an ignore rule does not remove it from Git history,
  remote caches, forks, existing clones or previously published releases.

## Secret checks

The Secret scan workflow scans fetched Git history with a pinned Gitleaks version
and verified archive checksum. Output is redacted. `.gitleaks.toml` permits only
one exact, nonfunctional redaction-test value in four named test files; it does
not exclude tests as a category.

Before publishing additional branches, releases, installers or artifacts, review
their contents separately. These can expose files that are not in the source tree.
Never use a public issue to report an actual credential or share personal logs.
