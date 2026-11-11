# Gaming chat overlay

## Launch and use

Run the current source with `.\run.ps1 --gui`. Keep Jarvis running while playing.
Press **Ctrl+Alt+Space** to toggle Game Chat, or open **Settings > Game Chat**.
Escape and the close icon hide it. Enter the game name and optional context
(map, mode, rank, build), type a question and press Enter. The game is not
detected automatically. Opening the chat takes keyboard focus from the game;
it does not pause multiplayer matches.

Examples:

- Game: Valorant; Context: Ascent, defender. "How should I defend B with Killjoy?"
- Follow-up: "What if they rush?"
- Game: Minecraft. "Как да намеря диаманти?"
- Enable Web search: "What changed in the latest patch? Give official sources."

Uses the configured chat model and conversation language (English, Bulgarian
or auto). Requires working OpenAI API access; normal API charges apply. There is
no separate model subscription bundled here. Selecting Web search makes the
Responses web-search tool available; links come from response citation metadata.
No cited source means current facts have not been substantiated by citations.
Click source links deliberately; they open through Windows' default URL handler.

## Voice conversation

Choose the game and context, then **Voice**. Confirm microphone use once for that
call. The selected Live model, voice and language come from Settings. Talk normally;
use the microphone toggle to mute, the interrupt button to stop Jarvis speaking,
and the call button to end the call. Text and voice requests do not run concurrently.

Optionally check **Share screen** before starting: consent then includes periodic
primary-monitor images sent to OpenAI until Stop. This is not continuous video.
Hide Game Chat with Ctrl+Alt+Space or Escape to return to the game: the call keeps
running until you stop it, change game/context, clear the discussion, or exit Jarvis.
The screen-sharing indicator also stops image transmission independently of audio.
Do not cover the game with the chat when asking about the visible scene.

Changing Web search stops the call; start it again to use the new selection.
The voice model can request sourced advice through a dedicated read-only game tool;
it has no game-control, file-editing or laptop-action tools. Text and voice sessions
currently have separate conversational context; a new call starts a fresh session.

## Boundaries

- A normal always-on-top Windows tool window, not an injected game overlay.
  Use windowed/borderless mode. Exclusive fullscreen, reserved game shortcuts,
  elevated windows and anti-cheat policies may prevent showing/focusing it.
  Never disable anti-cheat or security protections to make the overlay work.
- No process/game-memory reading, game control or automatic game detection.
  Microphone and screen access require the explicit voice opt-in described above.
- Only submitted game/context/questions and up to ten recent turns go to the
  text model. Voice also receives microphone audio and optional screen images.
  No router action tools, files, saved personal memory or email access.
- Discussion remains in this process only. Changing game/context or clearing
  the discussion resets it. Closing Jarvis drops it. `store=False` is requested,
  but is not a promise of zero provider retention.
- One request at a time, no automatic retries, bounded input/output and a
  45-second SDK request timeout. Stop discards the pending answer, not necessarily
  the provider request or charges. A new request waits for that worker to finish.
  Closing/hiding does not bring the window back when an answer arrives.
- Settings has a persistent enable/disable checkbox for this shortcut. A binding
  conflict reports a notification and leaves the Game Chat button working.
  Existing Ctrl+Space voice and Alt+Space command overlay bindings are unchanged.

## Manual acceptance

1. Start Jarvis, press Ctrl+Alt+Space twice; show then hide exactly once per press.
2. Open with the Settings button, choose the actual game and ask a basic question.
3. Ask a follow-up; verify the answer uses the previous discussion.
4. Switch game; verify the earlier game discussion is cleared.
5. Select Bulgarian in Settings and ask a Bulgarian question.
6. Enable Web search for a patch question; inspect cited sources and dates.
7. While waiting, Stop/Clear/change game; the old answer must not reappear.
8. Hide with Escape during a request; completing the answer must not steal focus.
9. Repeat from a borderless game; record focus/shortcut behavior for that game.
10. Disable the shortcut in Settings; verify the button still opens the chat.
11. Exit Jarvis; the shortcut must be released.
12. Start Voice without screen sharing; discuss the chosen game, mute and interrupt.
13. Enable Share screen, start a new call, hide the panel and ask about the game.
14. Stop images from the sharing indicator; Jarvis must not receive new frames.
15. End the call, reopen it, and change game/context; stale replies must not return.

Automated tests use fake model responses and Qt offscreen windows. They do not
establish live game compatibility, answer quality or account/model availability.
No new installer is built by this increment.

API reference: https://developers.openai.com/api/docs/guides/tools-web-search
