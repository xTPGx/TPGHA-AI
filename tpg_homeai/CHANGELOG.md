# Changelog

## 1.0.15

- Added household user roles: admin, manager, resident, and guest.
- Cleaned up the TPG HomeAI sidebar so residents see Jarvis operation pages instead of admin/config/debug tools.
- Added a View As selector to test role-specific UI modes and made Users editable with role selection.
- Added a UI session endpoint that can use Home Assistant/proxy user headers when available and falls back to configured users.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.14

- Added a Conversation Notebook page for browsing past Chat sessions inside TPG HomeAI.
- Added per-session notes and Markdown export so brainstorming sessions can be downloaded and shared with ChatGPT or docs.
- Added a read-only web research/search layer and wired search context into general OpenAI conversation for current/latest questions.
- Added Notebook + Research as a first-class Jarvis Brain readiness layer.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.13

- Fixed the Brain Overall score so completed layers can actually reach 100% instead of being permanently capped below full readiness.
- Made pending proactive suggestions stop lowering readiness when the proactive suggestion engine itself is already implemented.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.12

- Split wake-word readiness into two clear concepts: assistant wake phrases configured versus real voice sources deployed.
- Updated Brain, Home Brain, and Setup wording so the live-house blocker points to missing microphones/panels/HA Assist sources, not missing assistant wake phrases.
- Added an empty-state callout in Assistant wake deployment explaining how to add a real voice source.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.11

- Upgraded the OpenAI Python SDK to support `gpt-4o-mini-tts` voice instructions.
- Fixed OpenAI TTS falling back to browser because the old SDK rejected the `instructions` parameter with `TypeError`.
- Added a compatibility retry that strips `instructions` if an older SDK is accidentally installed.
- Improved voice fallback diagnostics so the UI reports the real sanitized OpenAI/SDK error instead of only the exception type.
- Added regression coverage for the SDK `instructions` mismatch.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.10

- Moved wake-word and voice-source deployment management into the Assistant page.
- Removed Voice Sources from the main navigation; old `/voice-sources` links now redirect to Assistants.
- Kept Brain as the single Jarvis/Home intelligence area; old `/house-brain` links now redirect to Brain.
- Updated first-run setup links so wake-word setup sends users to Assistants instead of a separate voice-source page.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.9

- Moved voice testing, preview, and voice catalog into the Assistant editor.
- Removed Voice Settings from the main navigation; old `/voice-settings` links now redirect to Assistants.
- Added voice-profile overrides to preview/test endpoints so unsaved assistant editor voice choices can be tested directly.
- Clarified UI language so `browser` is shown as playback destination, not mistaken for the TTS provider.
- Upgraded legacy saved assistant voice profiles like `browser / neutral` to the new OpenAI defaults for Atlas and Chatty.
- Added regression coverage to ensure editor voice overrides preserve the selected OpenAI voice profile.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.8

- Moved wake-word identity onto Assistant profiles with editable `wake_words` and `listen_enabled`.
- Added optional assistant binding on Voice Sources so microphones, panels, and satellites deploy a specific assistant into a room.
- Updated Assistants UI to edit wake words, show linked voice sources, and display resolved OpenAI voice defaults instead of misleading legacy aliases.
- Updated wake-word readiness to report assistant readiness and physical source deployment separately.
- Seeded Atlas/Chatty wake words and sample source bindings in starter config.
- Added regression coverage for assistant wake-word saves and Brain wake-word assistant readiness.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.7

- Added a guided Setup page for first-run readiness across HA, OpenAI, users, rooms, music, voice sources, and permissions.
- Added validated backend config-management endpoints for users, music accounts, speakers, and permissions.
- Added Add/Edit UI flows for Users, Music Assistant accounts, speaker mappings, and Permissions policy.
- Kept security policy explicit: low-risk confident actions can run, while sensitive actions remain confirmation/PIN gated.
- Added regression coverage for the new management endpoints and Setup ingress route.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.6

- Added backend config-management endpoints for rooms, assistants, and voice sources.
- Added Add/Edit UI flows for Rooms, Assistants, and Voice Sources so key setup no longer requires YAML editing.
- Combined Jarvis Brain and House Brain into one Brain menu item with Jarvis/Home tabs.
- Added regression coverage for web UI config upserts and runtime reload.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.5

- Fixed upgraded installs where old `voice: neutral` assistant config forced Atlas/Chatty back to browser `alloy`.
- Known assistant defaults now resolve Atlas to OpenAI Cedar and Chatty to OpenAI Coral unless explicitly overridden.
- Added voice regression checks so configured assistant profiles do not silently degrade to browser voice profiles.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.4

- Routed the Home Assistant Assist conversation agent through `/chat` so voice uses the full conversational brain, not only the command parser.
- Improved HA integration errors so backend HTTP failures include useful server detail.
- Fixed general conversation history logging to use resolved assistant/user IDs for better context continuity.
- Hardened action policy so read-only status, security, query, and dashboard lookup responses do not appear as physical executions.
- Made dashboard-open responses honest about path lookup versus actual Browser Mod navigation.
- Added regression coverage to keep HA Assist on the chat brain and protect dashboard proposal mode.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.3

- Fixed status/query commands so they no longer appear as executed physical actions.
- Treated dashboard drafts as backend proposal-required actions, matching the Chat UI.
- Included normal `service_call` audit data in policy risk analysis, not only preview calls.
- Added first-class speaker support for optional Music Assistant player entity IDs.
- Relaxed media playback outcome checks to handle common Home Assistant player states.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.2

- Routed explicit music requests through Music Assistant first, including playlist/album/artist/track wording.
- Fixed playlist names like “This Is Mitchell Tenpenny” being mistaken for a follow-up pronoun command.
- Added standard service-call audit data for music playback so the outcome verifier can check the target speaker.
- Added Music Assistant REST helpers with media-player fallback when the Music Assistant integration is unavailable.
- Added acceptance coverage for natural Spotify playlist playback on the office speaker.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.1

- Added a true general conversation brain for advice, brainstorming, normal Q&A, and non-HA chat.
- Updated `/chat` so non-action messages fall through to OpenAI/general conversation instead of failing as unmapped commands.
- Added Home Assistant weather-context support for weather questions when HA exposes weather entities.
- Added `draft_dashboard` as a guarded AI tool for natural requests like “build a dashboard for the office.”
- Updated Chat UI language to support “ask anything” use, not only device commands.
- Added acceptance coverage for general chat and dashboard drafting.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 0.1.32

- Added `/brain/completion` with Jarvis v1 software readiness, live-house deployment gates, blockers, and stop criteria.
- Added a Jarvis v1 Completion panel to the Jarvis Brain UI so the system shows when feature work should stop.
- Added Home Assistant `get_completion_status` service for dashboards, scripts, and diagnostics.
- Split completion into software ship readiness versus real-house deployment readiness.
- Added acceptance coverage for the completion endpoint.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 0.1.31

- Added a configurable house mode brain for home, away, sleep, movie, guest, cleaning, and security behavior.
- Added `/brain/modes` with active mode inference, reply policy, safe auto-execute posture, and confirmation gates.
- Added `/voice/deployment` with wake-word/source readiness, missing source identity checks, speaker route checks, and room satellite recommendations.
- Added Mode Brain and Wake Word Deployment panels to the House Brain UI.
- Added Home Assistant services for mode brain and wake-word deployment diagnostics.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 0.1.30

- Added voice source trust, user, default reply, and speaker routing metadata for Assist satellites, panels, and microphones.
- Added room-aware reply routing for assistant speech: browser, quiet, explicit media player, or room speaker.
- Added `/brain/house-state`, `/brain/assistants`, and `/dashboards/tablet-profiles` endpoints for situational awareness and management.
- Added a House Brain UI showing modes, presence, security/energy/media/maintenance attention, rooms, assistants, and tablet panels.
- Expanded dashboard drafts with optional tablet/profile and voice-panel views.
- Added starter voice source templates for office, kitchen, bedroom, and living room deployments.
- Expanded proactive scans with repeated-command learning suggestions and away-mode climate recommendations.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 0.1.29

- Added assistant voice profiles with provider, model, voice, instructions, output, and fallback settings.
- Added OpenAI TTS speech generation with browser speech fallback for Atlas, Chatty, and future assistants.
- Added `/voice/profiles`, `/voice/voices`, `/voice/preview`, `/voice/speak`, and `/voice/audio/{id}` endpoints.
- Added a Voice Settings UI for testing configured assistant voices and provider readiness.
- Updated Chat to play configured assistant speech instead of hardcoded browser-only voices.
- Added add-on options for OpenAI TTS model/format and optional HA speaker routing base URL.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 0.1.28

- Added a device adapter map at `/knowledge/device-adapters` for fan presets, media players, lights, locks, and personal devices.
- Added recovery guidance to repair suggestions when post-action verification does not match expected state.
- Added a Memory Center UI for drafting, approving, and ignoring learned house/user/device preferences.
- Added a Dashboard Builder UI for generating and installing Lovelace YAML from approved HomeAI configuration.
- Added a Voice Sources UI plus `/knowledge/voice-sources` so room-aware microphone/panel mappings are visible.
- Expanded Device Profiles with adapter and recovery hints.
- Added ingress/API regression checks for the new Jarvis management pages and endpoints.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 0.1.27

- Added voice source mappings so commands can infer room context from a panel, satellite, or microphone source.
- Added outcome verification details to Chat so executed actions show post-action state checks.
- Added a Device Profiles UI for capabilities, quirks, entity grouping, and action history.
- Added proactive and repair suggestions to the Suggestions approval inbox.
- Added AI provider routing visibility to the Jarvis Brain page.
- Expanded dashboard drafts with Devices and voice-source views plus HA service support.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 0.1.26

- Added router-level outcome verification so executed commands record post-action HA state checks.
- Added repair suggestions when an action executes but the follow-up state does not match.
- Added device profile generation with capabilities, quirks, and success/failure history.
- Added `/knowledge/device-profiles` plus a Home Assistant service for profile data.
- Added actual Ollama-compatible local model tool selection fallback.
- Expanded proactive monitoring for away-mode lights and low-battery findings.

## 0.1.25

- Added room/source context fields for room-aware commands from Chat, HA services, and Assist surfaces.
- Added optional security PIN enforcement for critical confirmations such as unlock.
- Added physical-device grouping so noisy HA entities can be treated as real devices.
- Added correction-to-memory drafting for successful user corrections.
- Added command-history routine mining to proactive suggestions.
- Added AI provider readiness for OpenAI, optional Ollama configuration, and deterministic fallback parser.
- Added HA-native services for Jarvis layers, physical devices, and AI provider status.

## 0.1.24

- Added a backend action policy brain that labels every command/preview as execute-now, confirmation-required, proposal-required, review-required, clarify, or answer-only.
- Added a live seven-layer Jarvis readiness map at `/brain/layers`.
- Added a Jarvis Brain UI page showing policy, capability graph, conversation memory, voice, proactive suggestions, HA-native UI, and AI hybrid readiness.
- Updated Chat to use backend `data.policy` decisions instead of frontend-only preview guessing.
- Added regression checks for the brain endpoint and safe-vs-sensitive policy decisions.

## 0.1.23

- Updated Chat safety flow so confident low-risk commands execute immediately.
- Kept review/confirmation for sensitive, uncertain, and proposal actions.
- Adjusted Chat UI copy from preview-all to review risky or uncertain commands.

## 0.1.22

- Added vetted media_player turn_on/turn_off service planning for TV/display power commands.
- Added deterministic generic power routing for commands like "turn on office TV".
- Added Tuya/Smart Life fan fallback from percentage requests to preset modes.
- Improved fan-speed follow-up context for requests like "turn up fan speed".
- Added regression checks for Office TV power and Tuya-style fan speed control.

## 0.1.21

- Rebuilt Chat around preview-first action execution.
- Added Execute, Request confirmation, Confirm, and Cancel controls in chat.
- Kept browser voice input flowing through the same safe preview path.
- Made automation and routine previews side-effect free so dry-runs do not create drafts.

## 0.1.20

- Added dry-run command preview endpoints for safe action planning.
- Added a recording Home Assistant client so previews resolve real targets without executing services.
- Added preview confirmation handling that reports sensitive actions without creating live tokens.
- Added Home Assistant `preview_command` service for dashboards, scripts, and voice UX.

## 0.1.19

- Added command audit persistence with selected tool, resolved target, result data, and errors.
- Added an `explain_last_action` tool so TPG HomeAI can answer why it did something.
- Added `/debug/commands` and `/debug/last-command` backend endpoints.
- Added Home Assistant services for recent command audit data.
- Added additive SQLite migrations for upgraded command history fields.

## 0.1.18

- Added approved automation draft installation into Home Assistant automations.yaml.
- Added routine draft builder for movie, bedtime, morning, away, and security routines.
- Added proactive monitor scan for security, maintenance, and sleep-timer suggestions.
- Added dashboard YAML install endpoint and Home Assistant services for new actions.
- Added additive SQLite migrations for persisted add-on upgrades.

## 0.1.17

- Added persisted short-term conversation context for follow-up commands.
- Added pronoun handling for phrases like "turn it off" and "dim it to 40".
- Added correction handling for phrases like "actually the fan".

## 0.1.16

- Added browser microphone dictation and spoken replies to the Chat page.
- Added command direction guardrails so explicit on/off wording cannot invert.
- Added acceptance checks for light on/off direction correction.

## 0.1.15

- Added support for Home Assistant's `/api/hassio_ingress/<token>` URL shape.
- Kept API calls scoped to the add-on while running inside HA ingress.
- Added regression checks for HA ingress wrapper API and asset paths.

## 0.1.14

- Added frontend API base fallback for HA Supervisor ingress variations.
- Added backend normalization for direct ingress-prefixed API paths.
- Added regression checks for both `/slug/api/health` and `/slug/health`.

## 0.1.13

- Fixed Home Assistant add-on ingress frontend loading.
- Made built frontend assets relative so they load under Supervisor ingress.
- Routed frontend API calls through ingress-safe `/api` paths.
- Added regression checks for ingress root, frontend routes, API calls, and assets.

## 0.1.12

- Added Home Assistant registry enrichment through the HA WebSocket API.
- Added the house knowledge graph API.
- Added approval-first memory and proactive suggestion persistence.
- Added Home Assistant services for knowledge graph, memory, and suggestions.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 0.1.11

- Added Home Assistant ingress/sidebar metadata for the add-on.
- Added HA-native dashboard draft and Browser Mod panel services.
- Added Lovelace dashboard draft generation.
- Improved Discovery cards with device/source/category details and contextual actions.

## 0.1.10

- Added conversational chat and suggestion proposal endpoints.
- Added automation draft approve/edit/ignore workflow.
- Improved sleep timer and scheduled brightness draft generation.

## 0.1.6

- Earlier public add-on build used by Home Assistant before the current update
  metadata refresh.
