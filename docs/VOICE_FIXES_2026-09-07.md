# Voice Greeting Fixes

## Confirmed Problems

- Router tests used default relative persistence paths and wrote synthetic chat/research replies into real conversation history. Those records could then be sent as context in a live call.
- Realtime microphone audio was transmitted during speaker playback without acoustic echo cancellation. Self-listening is a plausible cause of the reported repeated greetings; actual room acoustics were not recorded during diagnosis.
- Startup TTS and the first Realtime response could both issue the same introduction. Classic speech queued behind the live microphone lock could play after a call ended.
- Interrupted audio was discarded, but late transcript events could still replace the visible caption. Late completion of an older response could release a newer response's busy state.

## Changes

- All pytest tests get an isolated working directory and no inherited OpenAI API key. Local test fixtures may still set explicit mock keys. Conversation history was byte-identical before and after the final suite.
- A bounded one-time migration removed 67 exact known September 6 fixture records and preserved 13 other records. Full original backup: `data/development-backups/conversation-before-repair-20260907T105618858452.jsonl`. The migration is not installed as a runtime conversation filter.
- The default Speakers setting gates outgoing microphone PCM during pending speaker audio and 300 ms beyond its scheduled DAC completion. Muted/echo-era queued input cannot leak after the gate reopens. This is half-duplex prevention, NOT acoustic echo cancellation.
- Headphones mode leaves audio input live for voice interruption. Settings changes apply on the next call.
- The skip icon interrupts only the spoken response, keeping the call open. It cancels generation, drops pending audio, truncates unheard server context, and rejects late captions/audio. Task cancellation remains separate.
- Classic speech is suspended and its queued jobs invalidated during live calls. A started/completed startup greeting suppresses the duplicate live introduction.
- Default voice instructions favor concise Bulgarian replies and discourage repeated greetings or habitual enthusiastic fillers. Custom user instructions remain respected.

## Verification

- `python -m pytest -q --basetemp=data/diagnostics/pytest-voice-verified`: **866 passed, 4 skipped**, two existing SpeechRecognition deprecation warnings.
- `python tools/check_realtime_connection.py --conversation --audio-greeting`: live API accepted the current configuration with 83 GUI tool schemas. Synthetic Bulgarian PCM saying "Здравей Джарвис" triggered semantic VAD and the spoken reply "Здрасти! Как си днес и с какво да помогна?". Casual follow-up and context recall also returned audio. Arbitrary URL intent and read-only GUI task status passed; no website or computer action was executed.
- `python tools/render_voice_ui.py`: native screenshots at 960x720, 1360x850 and 1920x1080 plus speaking/error states; inspected the speaking image and new interrupt control.
- The generated greeting is `data/diagnostics/realtime-greeting.wav` (3.10 seconds). No physical microphone was opened by the API diagnostic.

## Local Test

Run `.\run.ps1 --gui`, press play, and wait for LISTENING. Say "Здравей Джарвис", then ask a normal follow-up question. On laptop speakers, wait until the reply finishes or use Interrupt reply before speaking. With actual headphones, select Settings > Voice > Live audio mode > Headphones and reconnect to test spoken interruption.

Real microphone quality, audible output, and room echo still require a human listening test. No claim is made that this is full ChatGPT Voice or a complete acoustic echo-cancelling transport. Source changes do not rebuild an older packaged installer.

Protocol reference: [OpenAI Realtime conversations and interruptions](https://developers.openai.com/api/docs/guides/realtime-conversations).
