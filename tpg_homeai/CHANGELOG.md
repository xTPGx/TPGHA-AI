# Changelog

## 1.0.47

- Added Automation Builder v9 one-off date awareness so phrases like "tomorrow at 7 PM", "next Monday", "June 30", and "6/30" draft dated Home Assistant template conditions.
- Kept recurring weekday behavior for recurring requests while preventing one-off date requests from silently becoming forever automations.
- Removed date words from action parsing so dated scheduled tasks still resolve the intended device/action cleanly.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.46

- Added Automation Builder v8 interval triggers so phrases like "every 15 minutes" and "every hour" draft native Home Assistant `time_pattern` automations.
- Prioritized interval parsing ahead of loose time parsing so numbers in interval requests are not mistaken for clock times.
- Added readable interval trigger summaries for automation previews and suggestion cards.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.45

- Added notification automation drafting so requests like "notify me when the front door unlocks" create approval-first `persistent_notification.create` actions.
- Added timed temporary action drafting so requests like "turn on the office fan for 10 minutes" create an action, delay, and safe reverse action sequence.
- Expanded deterministic fallback routing so notification/reminder automation requests work without depending only on OpenAI tool selection.
- Updated Jarvis Brain readiness evidence for notification and temporary-action automation composition.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.44

- Added Automation Builder v5 time-window conditions so natural language like "between 10 PM and 6 AM", "after 9 PM", and "before 7 AM" becomes native Home Assistant time-condition YAML.
- Added entity state guard conditions so requests like "only if the office light is off" or "only if the front door is locked" draft guarded automations instead of unconditional actions.
- Expanded automation trigger/condition matching to include mapped room lights, fans, speakers, and displays.
- Improved automation summaries so time windows and state guards are readable in previews.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.43

- Added Automation Builder v4 state/event triggers so natural language like "when the front door unlocks" drafts native Home Assistant state-trigger YAML.
- Added numeric sensor threshold triggers so requests like "when the front door battery drops below 20" draft `numeric_state` automations instead of being mistaken for time schedules.
- Expanded trigger entity matching across approved locks, battery sensors, security sensors, device aliases, room devices, and personal devices.
- Improved automation draft previews and Jarvis Brain readiness evidence for state/numeric triggers.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.42

- Expanded Automation Builder v3 with weekday/weekend recurrence, richer fan percentage/level, climate temperature, cover/garage, lock, and switch action drafting.
- Added parsed automation draft summaries and warnings so Suggestions shows triggers, conditions, actions, and install readiness before approval.
- Added Dashboard Architect v2 natural-language dashboard briefs, template selection, room/template inference, and architect summaries.
- Kept dashboard/chat dashboard changes approval-first; admin/manager dashboard role gates remain enforced.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.41

- Removed stale browser `sessionStorage` as an active Home Assistant identity source so a previous Shawn/Jordie/Kiosk login cannot keep poisoning the current TPG profile.
- Made the Home Assistant sidebar panel detect active HA user changes, refresh the iframe hash, and keep posting the current HA user into TPG HomeAI.
- Added Chat voice session runtime UI with listening/transcribing status, elapsed recording time, last transcript display, and a real cancel path that discards captured audio instead of sending it.
- Added verifier coverage for stale identity prevention, panel identity refresh, and voice session cancel/status behavior.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.40

- Added actionable Chat microphone diagnostics for blocked permissions, HTTP/insecure origins, localhost confusion, missing microphones, and unsupported browsers.
- Added an in-chat "Diagnose mic" action so Home Assistant app/browser voice readiness can be checked directly after a failure.
- Expanded Setup with voice runtime readiness and local browser/app microphone environment checks.
- Added a Dashboard Builder pre-install preview showing generated views, card counts, and approved spatial asset coverage before installing YAML.
- Added editable automation draft YAML in Suggestions so scheduled tasks can be reviewed and corrected before installation.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.39

- Added the House Spatial Brain: approved floor plans, blueprints, room photos, and notes are grouped by room with dashboard hints, automation ideas, mapping questions, and coverage status.
- Added `/house/spatial-brain` and `/voice/runtime` APIs for deployable room knowledge and assistant/source voice runtime readiness.
- Dashboard drafts now include AI Layout Notes from approved house knowledge assets so generated dashboards are informed by real floor plans and room notes.
- Upgraded automation drafting for multi-action scheduled tasks with time, delay, sunset, sunrise, and presence conditions while keeping install approval-first.
- Added House Knowledge UI spatial readiness cards and expanded Jarvis Brain readiness layers for spatial brain, dashboard architect, automation builder v2, personal profiles, and voice runtime.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.38

- Added a House Knowledge workspace for floor plans, blueprints, room photos, and layout notes.
- Added `/house/assets` upload/list/detail/file/approve/ignore APIs with durable storage under the add-on config directory.
- Added approval-first asset analysis: drafts can be reviewed, and only approved assets become active AI house context.
- Injected approved house assets into general Chat context for room, zone, dashboard, map, blueprint, and floor-plan questions.
- Added House Knowledge to the admin/manager UI, Setup checklist, Jarvis Brain readiness map, and backend regression coverage.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.37

- Added smart chat auto-scroll so new user/assistant messages stay visible while preserving the user's place when they scroll up through history.
- Added a "Jump to latest" affordance when reading older chat history.
- Added soft-archive delete for Recent chats: conversations disappear from the chat list without deleting the underlying command/audit transcript.
- Added backend `DELETE /conversations/{conversation_id}` support and regression coverage proving archived conversations are hidden from lists while detail/export history remains preserved.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.36

- Raised the add-on security rating from 7 to 8 by shipping a dedicated `apparmor.txt` profile (the add-on now runs under its own AppArmor confinement instead of the unconfined default).
- Added an optional `api_token` add-on option that guards direct (non-ingress) LAN access to port 8088; Home Assistant ingress requests stay exempt because they are already HA-authenticated, and health/TTS-audio/static paths remain public.
- Enforced `voice_sources` trust levels: `outside` sources can no longer trigger state-changing actions and `guest` sources are blocked from sensitive actions (locks, etc.); previously trust level was documentation-only.
- Low-confidence device commands now route into the confirmation flow (via a dry-run preview) instead of silently executing, so uncertain matches ask before acting.
- Smarter brain: ambiguous device matches ("the office lamp or the office ceiling light?") now ask for disambiguation; compound requests ("dim the lights and play jazz") are split and gated per step; named songs/artists resolve through Music Assistant search; and a live house-state summary plus the last few conversation turns are fed into tool selection so "turn off the light that's on" works.
- Voice satellites: the satellite's `source_device_id`/`source_entity_id` now selects the room's assistant (and its OpenAI voice) from `voice_sources`, instead of a fixed assistant.
- Hands-free panel mode: tablets/old phones on Chrome/Android can run an always-listening browser wake-word loop (with a listening indicator and optional room context); iOS Safari stays on tap-to-talk push-to-talk. The microphone button now also lives in the composer.
- UI: near-black ChatGPT-style theme (replacing the old navy/sky palette), neutral message bubbles, a unified rounded composer, lightweight markdown rendering for assistant replies, and a typing indicator while a reply is pending.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.35

- Fixed the active Home Assistant user not being resolved (e.g. logging in as Shawn but seeing Jordie/Chatty).
- The backend now treats the Home Assistant Supervisor ingress headers (`X-Remote-User-Id`, `X-Remote-User-Name`, `X-Remote-User-Display-Name`) as the authoritative, per-request identity of the active logged-in user. These are server-side and cannot be overridden by stale browser storage.
- Identity precedence reordered to: Supervisor ingress headers, then live HA parent user, then verified token, then legacy proxy headers. Browser `sessionStorage` is now only a last-resort hint.
- Retired the custom-element sidebar wrapper that iframed a hardcoded ingress path and reused a stale ingress session (the root cause of the wrong-user bug). The add-on now publishes a native Supervisor ingress sidebar panel (`panel_title`/`panel_icon`/`panel_admin: false`), which creates a fresh per-user session on every open.
- Added a `/ui/session/debug` endpoint and an in-app "Identity Debug" page (visible to all roles) that show the app version, request path, ingress headers, parsed candidates per source, the resolved TPG user, and `identity_source` so identity can be verified inside a real Home Assistant install.
- Fixed admin-header detection to also honor `X-Hass-Is-Admin`.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.34

- Replaced the raw add-on iframe sidebar ownership with a Home Assistant custom panel wrapper.
- The wrapper receives `hass.user` from Home Assistant and injects the active HA user into TPG HomeAI before the UI session is resolved.
- Added frontend support for wrapper-delivered HA identity through URL hash, session storage, and live postMessage updates.
- Kept add-on ingress enabled while removing the native add-on sidebar metadata so the custom integration owns the visible sidebar entry.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.33

- Fixed TPG HomeAI UI identity so the live Home Assistant frontend user wins over stale stored browser tokens.
- Removed broad localStorage token scanning that could reuse a previous Jordie/Kiosk/Shawn session in the HA iframe.
- Updated Chat, Assistants, Memory, Notebook, and the app shell to send the same live HA session hint.
- Added regression coverage for the exact stale-token case where HA is logged in as Shawn but an old token resolves Jordie.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.32

- Fixed TPG HomeAI UI identity detection so stale generic proxy headers cannot force all Home Assistant logins into the wrong TPG profile.
- Added verified Home Assistant current-user session detection using the active HA access token when available.
- Updated Chat and the app shell to resolve Shawn/Jordie/Kiosk from the same verified session path.
- Added regression coverage for Shawn, Jordie, and Kiosk verified identity mapping plus stale `x-forwarded-user` protection.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.31

- Replaced mobile chat microphone handling with a real browser recording path that uploads audio to `/voice/transcribe`.
- Added OpenAI speech-to-text support with clear fallback/error messages when the API key, microphone permission, or HTTPS requirement is missing.
- Kept Web Speech Recognition as a secondary fallback for browsers that support it.
- Added `openai_transcribe_model` add-on configuration with default `gpt-4o-mini-transcribe`.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.30

- Added backend-owned AI tool role policy so residents/kiosk/guests can keep normal conversation, brainstorming, device control, and schedule/automation drafting.
- Blocked non-admin users from AI-driven dashboard/view builder actions with an explicit `role_not_allowed` response instead of relying on hidden UI menus.
- Kept Shawn/Owner/Admin and manager roles able to draft dashboards and use the full management toolset.
- Added regression checks that Jordie can create scheduled automation proposals but cannot draft dashboards through Chat.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.29

- Stopped `/ui/session` from ever defaulting to Shawn/Owner when Home Assistant does not pass a trusted logged-in user identity.
- Changed missing identity fallback to the shared `House Remote` / `Jarvis` kiosk profile and exposed an `identity_warning` so the UI explains the issue instead of silently showing the wrong person.
- Added HA user-id header matching in addition to HA username matching for better ingress/proxy compatibility.
- Pointed the custom HA sidebar iframe at Supervisor ingress instead of the raw backend URL so the panel stays inside the HA auth path for non-admin users.
- Defaulted Chat's pre-session starter state to Jarvis/House Remote instead of Atlas/Shawn.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.28

- Bundled the matching `custom_components/tpg_homeai` integration into the Home Assistant add-on image.
- Synced the custom integration into `/config/custom_components/tpg_homeai` on add-on start so the non-admin `/tpg-homeai-app` sidebar panel can actually register after a Home Assistant restart.
- Added release checks that the add-on ships and installs the custom integration files needed by HA Users-group accounts.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.27

- Registered the all-user Home Assistant custom integration panel on a dedicated `/tpg-homeai-app` route so it no longer competes with the Supervisor add-on ingress panel.
- Removed both the legacy add-on panel path and the custom panel path before registering, preventing stale owner-only sidebar entries from blocking non-admin/mobile users.
- Updated the `open_panel` service default to `/tpg-homeai-app` so Browser Mod/tablet navigation uses the non-admin-safe route.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.26

- Replaced the Supervisor add-on sidebar panel with the custom integration iframe panel at `/tpg-homeai` when the integration loads.
- Fixed the owner-only sidebar behavior where HA admins could see TPG HomeAI but HA non-admin/mobile users could not.
- Kept the panel title and path unchanged while forcing `require_admin=False` and default sidebar visibility from the custom integration.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.25

- Preserved shared `kiosk` and guest roles when syncing Home Assistant non-admin users instead of flattening every HA non-admin into a resident profile.
- Made HA-linked shared profiles easier to understand on the Users page by showing the HA login and first-class `Kiosk / Shared` role badge.
- Hardened the custom integration sidebar panel registration so the TPG HomeAI iframe panel is explicitly visible to non-admin HA users.
- Added regression checks for non-admin sidebar metadata and HA `kiosk` sync behavior.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.24

- Rebuilt the Chat workspace into a full-height ChatGPT-style surface with a persistent conversation rail on tablet/desktop and a drawer on mobile.
- Removed the stacked history-above-chat layout that made HA ingress feel cramped and confusing.
- Tightened the global app shell with a quieter sidebar, full-width chat route, cleaner cards, polished scrollbars, and modern chat composer styling.
- Added prompt starters, sleeker message bubbles, and compact Notes access inside Chat.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.23

- Set add-on `panel_admin: false` so the native Home Assistant sidebar entry is available to HA non-admin users, not only owners.
- Rebuilt Chat as the primary ChatGPT-style Jarvis surface with automatic HA user/default assistant selection instead of visible assistant/user/room controls.
- Moved conversation history and Notebook notes/export into the Chat page so profile history is managed where the conversation happens.
- Defaulted spoken replies off in Chat while keeping a one-click voice toggle.
- Added in-chat scheduled-task flow: users can request an automation, review the draft, and install it into Home Assistant from the conversation.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.22

- Added Home Assistant user sync so HA Administrators become TPG Owner/Admin profiles and HA non-admin users become resident self-service profiles.
- Kept Home Assistant as the access authority while TPG profiles retain assistant identity, chat history, memory, voice, music account, and preference ownership.
- Added a Users-page sync action and disabled manual role editing for HA-synced profiles so access changes happen in Home Assistant.
- Allowed residents to edit only their own assistant and memory, with a fallback to create their own assistant if sync has not created one yet.
- Scoped resident Notebook loading to the detected HA user and assistant profile instead of briefly loading all conversations before session detection finishes.
- Matched UI sessions against HA username and HA user ID, not just friendly names and aliases.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.21

- Added normalized HA username matching so punctuation/spacing differences in HA login names are less likely to create the wrong TPG session.
- Exposed detected HA login candidates in the UI session for easier troubleshooting.
- Added an HA-admin authority override path so, when HA/proxy admin headers are available, Administrator sessions are treated as Owner/Admin in TPG HomeAI.
- Kept TPG profiles for assistant identity, memory, voice, and music ownership while allowing HA to own access level when it can provide it.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.20

- Added a global Back button in compact and wide layouts for easier Home Assistant panel navigation.
- Displayed admin sessions as Owner in the UI to match the household access model.
- Added owner lockout protection so saving users cannot remove the last Owner/Admin profile.
- Added runtime recovery for existing configs that accidentally have no Owner/Admin user, allowing the owner to regain the Users page and fix roles.
- Kept add-on, backend, Docker label, and custom integration versions aligned.

## 1.0.19

- Refactored the frontend into a responsive Home Assistant-friendly app shell with compact drawer navigation and wide-screen sidebar navigation.
- Reworked Chat into the primary Jarvis experience with premium conversation cards, clearer confirmations, and collapsed developer details.
- Cleaned up Dashboard, Discovery, Command Tester, Entities, Rooms, Music, Assistants, Permissions, Suggestions, Dashboard Builder, and HA Integration pages for mobile/tablet/desktop layouts.
- Replaced raw checkboxes with consistent toggles and moved raw JSON/YAML into collapsed developer panels.
- Kept backend behavior, APIs, add-on metadata, Docker label, and custom integration versions aligned.

## 1.0.18

- Added Jarvis as the shared AI profile for kiosk, wall panel, iPad, and house remote sessions.
- Made UI session responses include the active user's default assistant and all configured profiles.
- Made Chat default to the assistant/profile owned by the detected HA/TPG user instead of hardcoding Atlas/Shawn.
- Added profile-aware Notebook filtering so Atlas, Chatty, and Jarvis histories stay organized.
- Added Suggestions inbox detection for unknown HA/proxy users that need TPG AI profile setup.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.17

- Added a first-class kiosk/shared-user role for wall tablets, shared iPads, and room remotes.
- Seeded a House Remote user with normal house-control permissions but no admin/config access.
- Limited kiosk navigation to the shared-control surface instead of personal notebooks or setup pages.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

## 1.0.16

- Fixed role-aware navigation so the signed-in session role controls menu access.
- Replaced the sticky View As selector with a non-persistent admin-only Preview Menu selector.
- Prevented a saved browser preview value, such as Jordie/resident, from hiding Shawn/admin tools after reload.
- Kept backend, add-on, Docker label, and custom integration versions aligned.

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
