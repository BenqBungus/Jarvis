# Screen, gaming voice and settings integration

## Scope

This source upgrade reuses the Aurora desktop tokens and existing Realtime/audio
workers. No changes to Claude-owned voice workers, audio transports or Settings UI
source were required. No installer rebuild, personal capture, real microphone test
or paid provider request was performed during verification.

## Screen Chat

- Text discussion uses the configured chat model, not a hard-coded model override.
  Each submitted screen question captures a new primary-monitor image.
- Voice opens a separate Realtime session with explicit microphone/screen consent.
  Images are sent periodically while sharing is enabled. It is not video streaming.
- Commands off means discussion only. Commands on routes requested laptop actions
  through the existing command executor, safety checks and confirmations.
- Text commands can be submitted without sharing; they do not automatically attach
  an image. Project review tools remain part of the text discussion workflow, not
  implicitly available in the voice call.
- Mute, interrupt and stop controls are available. Closing Screen Chat ends its call.
  Clearing/stopping invalidates pending replies. A dismissed confirmation is not approval.
- Game Chat uses the same audio ownership controller; only one panel call can own
  the microphone. Starting one stops ordinary Live/classic conversation safely.

## Settings audit and fixes

| Control | Application path / behavior |
| --- | --- |
| Conversation language | Existing language adapters; new Live calls use saved language |
| Personality, humor, detail, address and role packs | Text prompt instructions now use personalization too |
| Chat model | Ordinary chat and Screen Chat both update on Save; blank resets default |
| STT provider/model and noise/pause thresholds | Existing STT instance updated when microphone is idle |
| TTS provider/model/voice | Existing speech instance updated at a safe idle boundary |
| Output device | Saved selection used by playback / next Live call |
| Live model/voice | Existing Realtime configuration read for each new call |
| Browser selection/path | Correct path loaded on browser switch; clearing removes old override |
| Website/app aliases | Shared settings consumed by existing router/actions |
| Confirmation/full-access settings | Existing permission gates retained; no automatic approvals added |
| Gaming app/process lists, mode volumes | Shared settings consumed by existing mode actions |
| Temperature threshold | Existing monitor reads saved preference |
| Startup/hotkeys | Existing handlers retained; Game Chat shortcut has its own saved toggle |
| Gmail account controls | Existing OAuth dialog retained; no mailbox access performed |

Audio changes wait until the current call ends rather than mutating an active
audio stream. Deliberate UI saves override process-local audio environment
overrides. The new natural-delivery prompt requests conversational pacing and fewer
repetitive greetings; custom TTS delivery instructions are preserved.

Automated checks verify wiring and state changes, not the actual availability of
each model, Windows voice, audio device, startup registration or game overlay.
Quality and latency still require an opt-in live acceptance test on the user's PC.

## Manual acceptance

1. Run `.\run.ps1 --gui`; open Settings and select language, Live voice and models.
2. Save, start a voice call and check that the chosen voice/language are used.
3. Change audio settings during a call: changes should wait until it ends.
4. Open Screen Chat > Voice and approve sharing. Ask about a visible editor error.
5. Interrupt, mute, unmute, then stop. No new audio or frames should be submitted.
6. Enable Commands, request a harmless website launch, and verify normal routing.
7. Request a disruptive action and decline its confirmation. It must not execute.
8. Press Ctrl+Alt+Space for Game Chat; choose a game and test Text, then Voice.
9. Opt into game screen sharing, hide the panel, and discuss the visible game.
10. Stop image sharing from its indicator; then stop the voice call separately.
11. Clear/switch game while a reply is pending; it must not reappear afterward.
12. Test windowed/borderless gameplay. Exclusive fullscreen compatibility is not
    promised; do not disable anti-cheat or inject anything into a game.

API access is billed separately. Selecting a model name in Settings does not prove
that the account has access to it or that it supports the selected modality.
