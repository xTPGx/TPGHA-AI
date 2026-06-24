import { useEffect, useMemo, useRef, useState } from "react";
import { api, CommandResponse } from "../api";
import PageHeader from "../components/PageHeader";

interface Msg {
  id: string;
  role: "user" | "assistant";
  text: string;
  mode?: string;
  kind?: "normal" | "preview" | "confirmation";
  command?: CommandResponse;
  originalText?: string;
}

type SpeechRecognitionCtor = new () => {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

function id() {
  return crypto?.randomUUID ? crypto.randomUUID() : `msg-${Date.now()}-${Math.random()}`;
}

function getSpeechRecognition(): SpeechRecognitionCtor | null {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

const PROPOSAL_INTENTS = new Set([
  "create_simple_automation",
  "create_routine",
  "draft_dashboard",
]);

const SENSITIVE_INTENTS = new Set([
  "unlock_door",
  "open_garage",
  "open_cover",
  "disarm_alarm",
  "disable_alarm",
  "disable_security",
  "disable_camera",
  "change_lock_code",
  "delete_automation",
  "remove_device",
]);

const SENSITIVE_ACTIONS = new Set([
  "unlock",
  "open",
  "disarm",
  "disable",
  "delete",
  "remove",
]);

const SENSITIVE_SERVICES = new Set([
  "lock.unlock",
  "cover.open_cover",
  "cover.open_garage_door",
  "alarm_control_panel.alarm_disarm",
]);

function commandConfidence(command?: CommandResponse) {
  const c = command?.resolved?.confidence;
  return typeof c === "number" ? c : 1;
}

function commandServiceNames(command?: CommandResponse) {
  const calls = command?.data?.preview?.service_calls;
  if (Array.isArray(calls) && calls.length > 0) {
    return calls
      .map((c: any) => `${c.domain || ""}.${c.service || ""}`.replace(/^\./, "").replace(/\.$/, ""))
      .filter(Boolean);
  }
  const tool = command?.tool_call || {};
  const name = typeof tool.name === "string" ? tool.name : "";
  const args = (tool.arguments || {}) as Record<string, any>;
  const domain = typeof args.domain === "string" ? args.domain : "";
  const service = typeof args.service === "string" ? args.service : "";
  return [`${domain}.${service}`, name].filter((v) => v && v !== ".");
}

function isSensitiveCommand(command?: CommandResponse) {
  if (!command?.intent) return false;
  if (SENSITIVE_INTENTS.has(command.intent)) return true;

  const args = (command.tool_call?.arguments || {}) as Record<string, any>;
  const action = String(args.action || args.service || "").toLowerCase();
  const domain = String(args.domain || command.resolved?.domain || command.resolved?.entity_id || "").toLowerCase();
  const serviceNames = commandServiceNames(command).map((s) => s.toLowerCase());

  if (serviceNames.some((name) => SENSITIVE_SERVICES.has(name))) return true;
  if (SENSITIVE_ACTIONS.has(action) && /lock|cover|garage|alarm|security|camera/.test(domain)) return true;
  return false;
}

function isUncertainCommand(command?: CommandResponse) {
  if (!command?.success || !command.intent) return false;
  const preview = command.data?.preview;
  const wouldExecute = Boolean(preview?.would_execute || command.tool_call);
  if (!wouldExecute) return false;
  if (commandConfidence(command) < 0.8) return true;
  const r = command.resolved || {};
  return Boolean(!r.entity_id && !r.label && !r.target && !r.door && !r.routine);
}

function shouldPauseForReview(command?: CommandResponse) {
  if (!command?.success || !command.intent) return false;
  const policy = command.data?.policy;
  if (policy && typeof policy.requires_review === "boolean") {
    return policy.requires_review;
  }
  return Boolean(
    command.requires_confirmation ||
      isSensitiveCommand(command) ||
      PROPOSAL_INTENTS.has(command.intent) ||
      isUncertainCommand(command),
  );
}

function serviceSummary(command?: CommandResponse) {
  const calls = command?.data?.preview?.service_calls || [];
  if (!Array.isArray(calls) || calls.length === 0) return "";
  return calls
    .map((c: any) => `${c.domain}.${c.service} ${c.data?.entity_id || ""}`.trim())
    .join(", ");
}

function outcomeLabel(command?: CommandResponse) {
  const outcome = command?.data?.outcome;
  if (!outcome) return "";
  if (!outcome.checked) return `Not checked: ${outcome.reason || "no verification needed"}`;
  return outcome.verified ? "Verified in Home Assistant" : "Needs review: state did not match";
}

function targetSummary(command?: CommandResponse) {
  const r = command?.resolved || {};
  return (
    r.label ||
    r.target ||
    r.entity_id ||
    r.door ||
    r.routine ||
    r.trigger?.platform ||
    ""
  );
}

export default function Chat() {
  const conversationId = useMemo(
    () => (crypto?.randomUUID ? crypto.randomUUID() : `chat-${Date.now()}`),
    [],
  );
  const [session, setSession] = useState<any>(null);
  const [config, setConfig] = useState<any>(null);
  const [assistant, setAssistant] = useState("atlas");
  const [user, setUser] = useState("shawn");
  const [room, setRoom] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const [speakResponses, setSpeakResponses] = useState(true);
  const [safePreview, setSafePreview] = useState(true);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const recognitionRef = useRef<InstanceType<SpeechRecognitionCtor> | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const speechSupported = Boolean(getSpeechRecognition());
  const users = session?.users || config?.assistants?.users || [];
  const assistants = session?.assistants || config?.assistants?.assistants || [];
  const selectedAssistant = assistants.find((a: any) => a.id === assistant);
  const selectedUser = users.find((u: any) => u.id === user);
  const canSwitchProfiles = ["admin", "manager"].includes(session?.role);

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
      audioRef.current?.pause();
      window.speechSynthesis?.cancel();
    };
  }, []);

  useEffect(() => {
    Promise.all([api.uiSession(), api.config()])
      .then(([sessionResult, configResult]) => {
        setSession(sessionResult);
        setConfig(configResult);
        const defaultUser = sessionResult.detected_user?.id || configResult.assistants?.users?.[0]?.id || "shawn";
        const defaultAssistant = (
          sessionResult.default_assistant?.id ||
          configResult.assistants?.assistants?.find((a: any) => a.owner === defaultUser)?.id ||
          configResult.assistants?.assistants?.[0]?.id ||
          "atlas"
        );
        setUser(defaultUser);
        setAssistant(defaultAssistant);
      })
      .catch(() => {
        /* keep safe starter defaults */
      });
  }, []);

  const browserSpeak = (message: string) => {
    if (!speakResponses || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(message);
    utterance.rate = 1;
    utterance.pitch = assistant === "chatty" ? 1.08 : 0.95;
    window.speechSynthesis.speak(utterance);
  };

  const speak = async (message: string) => {
    if (!speakResponses) return;
    setVoiceError(null);
    audioRef.current?.pause();
    window.speechSynthesis?.cancel();
    try {
      const response = await api.voiceSpeak({ assistant, text: message, room: room || undefined, reply_mode: "auto" });
      if (response.audio_base64 && response.content_type) {
        const audio = new Audio(`data:${response.content_type};base64,${response.audio_base64}`);
        audioRef.current = audio;
        await audio.play();
        return;
      }
      browserSpeak(response.speak_text || message);
    } catch (e: any) {
      setVoiceError(`Voice playback fell back to browser: ${e.message}`);
      browserSpeak(message);
    }
  };

  const appendAssistant = (msg: Omit<Msg, "id" | "role">) => {
    setMessages((m) => [...m, { id: id(), role: "assistant", ...msg }]);
  };

  const executeChat = async (message: string, appendUser = false) => {
    if (appendUser) {
      setMessages((m) => [...m, { id: id(), role: "user", text: message }]);
    }
    const r = await api.chat(assistant, user, message, conversationId, room || undefined);
    const command = r.command as CommandResponse | undefined;
    const response = r.response || command?.message || "Done.";
    appendAssistant({
      text: response,
      mode: r.mode,
      kind: command?.requires_confirmation ? "confirmation" : "normal",
      command,
      originalText: message,
    });
    void speak(response);
  };

  const send = async (override?: string) => {
    const message = (override ?? text).trim();
    if (!message) return;
    setText("");
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { id: id(), role: "user", text: message }]);
    try {
      if (safePreview) {
        const preview = await api.chatPreview(assistant, user, message, conversationId, room || undefined);
        const command = preview.command as CommandResponse | undefined;
        if (shouldPauseForReview(command)) {
          const response = preview.response || command?.message || "Preview ready.";
          appendAssistant({
            text: response,
            mode: preview.mode,
            kind: "preview",
            command,
            originalText: message,
          });
          void speak(response);
          return;
        }
      }
      await executeChat(message, false);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const executePreview = async (msg: Msg) => {
    if (!msg.originalText) return;
    setBusy(true);
    setError(null);
    try {
      await executeChat(msg.originalText, false);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (token: string) => {
    setBusy(true);
    setError(null);
    try {
      const needsPin = messages.some((m) => m.command?.confirmation_token === token && m.command?.data?.security?.pin_required);
      const pin = needsPin ? window.prompt("Enter security PIN") || "" : undefined;
      const r = await api.confirm(token, pin);
      appendAssistant({
        text: r.message || "Confirmed.",
        mode: r.executed ? "confirmed" : "confirmation",
        kind: "normal",
        command: r,
      });
      void speak(r.message || "Confirmed.");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async (token: string) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.cancelConfirm(token);
      appendAssistant({
        text: r.message || "Cancelled.",
        mode: "cancelled",
        kind: "normal",
        command: r,
      });
      void speak(r.message || "Cancelled.");
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const toggleListening = () => {
    setVoiceError(null);
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }

    const SpeechRecognition = getSpeechRecognition();
    if (!SpeechRecognition) {
      setVoiceError("Voice input is not supported in this browser.");
      return;
    }

    const recognition = new SpeechRecognition();
    recognitionRef.current = recognition;
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    let finalTranscript = "";

    recognition.onresult = (event: any) => {
      let interimTranscript = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += transcript;
        } else {
          interimTranscript += transcript;
        }
      }
      setText((finalTranscript || interimTranscript).trim());
    };
    recognition.onerror = (event: any) => {
      setVoiceError(event.error ? `Voice input failed: ${event.error}` : "Voice input failed.");
      setListening(false);
    };
    recognition.onend = () => {
      setListening(false);
      const transcript = finalTranscript.trim();
      if (transcript) {
        void send(transcript);
      }
    };

    setListening(true);
    recognition.start();
  };

  return (
    <div>
      <PageHeader title="Chat" subtitle="Ask anything, brainstorm, or control the house through guarded actions" />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select className="input max-w-[12rem]" value={assistant} onChange={(e) => setAssistant(e.target.value)} disabled={Boolean(session) && !canSwitchProfiles}>
          {assistants.length === 0 && <option value="atlas">Atlas</option>}
          {assistants.map((a: any) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
        <select className="input max-w-[12rem]" value={user} onChange={(e) => setUser(e.target.value)} disabled={Boolean(session) && !canSwitchProfiles}>
          {users.length === 0 && <option value="shawn">Shawn</option>}
          {users.map((u: any) => (
            <option key={u.id} value={u.id}>{u.name}</option>
          ))}
        </select>
        {(selectedAssistant || selectedUser) && (
          <div className="rounded-lg border border-slate-700 bg-slate-950/30 px-3 py-2 text-xs text-slate-400">
            Profile: <span className="text-slate-200">{selectedAssistant?.name || assistant}</span>
            {" "}· Owner: <span className="text-slate-200">{selectedUser?.name || user}</span>
          </div>
        )}
        <input
          className="input max-w-[12rem]"
          value={room}
          onChange={(e) => setRoom(e.target.value)}
          placeholder="Room context"
        />
        <button
          className={`btn-ghost min-h-[2.75rem] min-w-[2.75rem] ${listening ? "border-rose-400 bg-rose-500/20 text-rose-100" : ""}`}
          onClick={toggleListening}
          disabled={busy || !speechSupported}
          title={speechSupported ? "Use microphone" : "Voice input is not supported in this browser"}
          aria-label={listening ? "Stop listening" : "Start voice input"}
        >
          <span aria-hidden="true">{listening ? "■" : "●"}</span>
        </button>
        <label className="flex min-h-[2.75rem] items-center gap-2 rounded-lg border border-slate-600 px-3 text-sm text-slate-200">
          <input
            type="checkbox"
            checked={safePreview}
            onChange={(e) => setSafePreview(e.target.checked)}
          />
          Review risky or uncertain
        </label>
        <label className="flex min-h-[2.75rem] items-center gap-2 rounded-lg border border-slate-600 px-3 text-sm text-slate-200">
          <input
            type="checkbox"
            checked={speakResponses}
            onChange={(e) => setSpeakResponses(e.target.checked)}
          />
          Speak replies
        </label>
      </div>

      {error && <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}
      {voiceError && <div className="mb-4 rounded border border-amber-500/40 bg-amber-500/10 p-3 text-amber-100">{voiceError}</div>}

      <div className="card mb-4 min-h-[28rem] space-y-3">
        {messages.length === 0 && (
          <div className="text-slate-500">
            Known safe actions run immediately. Risky or uncertain requests pause for review.
          </div>
        )}
        {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "text-right" : "text-left"}>
            <div className={`inline-block max-w-[86%] rounded-lg border px-3 py-2 text-sm ${
              m.role === "user"
                ? "border-brand-dark bg-brand-dark/20 text-slate-100"
                : m.kind === "preview"
                  ? "border-cyan-500/60 bg-cyan-950/40 text-slate-100"
                  : "border-slate-700 bg-slate-950/60 text-slate-200"
            }`}>
              {m.mode && <div className="mb-1 text-xs uppercase text-brand">{m.mode}</div>}
              <div className="whitespace-pre-wrap">{m.text}</div>

              {m.command && (
                <div className="mt-2 grid gap-1 rounded border border-slate-700/70 bg-slate-950/50 p-2 text-xs text-slate-300">
                  {m.command.intent && <div><span className="text-slate-500">Intent:</span> {m.command.intent}</div>}
                  {targetSummary(m.command) && <div><span className="text-slate-500">Target:</span> {targetSummary(m.command)}</div>}
                  {serviceSummary(m.command) && <div><span className="text-slate-500">Would call:</span> {serviceSummary(m.command)}</div>}
                  {m.command.data?.policy?.decision && <div><span className="text-slate-500">Policy:</span> {m.command.data.policy.decision}</div>}
                  {m.command.data?.dashboard_draft?.view_count && (
                    <div className="text-cyan-200">
                      <span className="text-slate-500">Dashboard draft:</span> {m.command.data.dashboard_draft.view_count} view(s)
                    </div>
                  )}
                  {outcomeLabel(m.command) && (
                    <div className={m.command.data?.outcome?.verified === false ? "text-amber-200" : "text-emerald-200"}>
                      <span className="text-slate-500">Outcome:</span> {outcomeLabel(m.command)}
                    </div>
                  )}
                  {m.command.data?.outcome?.expected_state && (
                    <div><span className="text-slate-500">Expected:</span> {m.command.data.outcome.expected_state}</div>
                  )}
                  {Array.isArray(m.command.data?.outcome?.readings) && m.command.data.outcome.readings.length > 0 && (
                    <div className="mt-1 space-y-1">
                      {m.command.data.outcome.readings.map((reading: any) => (
                        <div key={reading.entity_id} className="rounded bg-slate-900/70 px-2 py-1">
                          {reading.entity_id}: {reading.state || reading.error || "unknown"}
                        </div>
                      ))}
                    </div>
                  )}
                  {m.command.data?.security?.pin_required && <div className="text-amber-200">Security PIN required</div>}
                  {m.command.requires_confirmation && <div className="text-amber-200">Confirmation required</div>}
                </div>
              )}

              {m.kind === "preview" && (
                <div className="mt-3 flex flex-wrap gap-2">
                  <button className="btn px-3 py-1.5 text-xs" onClick={() => void executePreview(m)} disabled={busy}>
                    {m.command?.requires_confirmation ? "Request confirmation" : "Execute"}
                  </button>
                  <button className="btn-ghost px-3 py-1.5 text-xs" onClick={() => appendAssistant({ text: "Cancelled.", mode: "cancelled" })} disabled={busy}>
                    Cancel
                  </button>
                </div>
              )}

              {m.kind === "confirmation" && m.command?.confirmation_token && (
                <div className="mt-3 flex flex-wrap gap-2">
                  <button className="btn px-3 py-1.5 text-xs" onClick={() => void confirm(m.command!.confirmation_token!)} disabled={busy}>
                    Confirm
                  </button>
                  <button className="btn-ghost px-3 py-1.5 text-xs" onClick={() => void cancel(m.command!.confirmation_token!)} disabled={busy}>
                    Cancel
                  </button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-3">
        <textarea
          className="input min-h-[4rem] flex-1"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          placeholder={listening ? "Listening..." : "Ask anything, brainstorm, or talk to the house..."}
        />
        <button className="btn self-stretch" onClick={() => void send()} disabled={busy}>
          {busy ? "Thinking..." : "Send"}
        </button>
      </div>
    </div>
  );
}
