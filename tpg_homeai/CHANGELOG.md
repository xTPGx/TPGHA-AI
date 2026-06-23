# Changelog

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
