import { useEffect, useMemo, useRef, useState } from "react";
import { api, CommandResponse } from "../api";
import Badge from "../components/Badge";
import Button from "../components/Button";
import DeveloperDetails from "../components/DeveloperDetails";

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

const PROPOSAL_INTENTS = new Set(["create_simple_automation", "create_routine", "draft_dashboard"]);
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
const SENSITIVE_ACTIONS = new Set(["unlock", "open", "disarm", "disable", "delete", "remove"]);
const SENSITIVE_SERVICES = new Set([
  "lock.unlock",
  "cover.open_cover",
  "cover.open_garage_door",
  "alarm_control_panel.alarm_disarm",
]);

function id() {
  return crypto?.randomUUID ? crypto.randomUUID() : `msg-${Date.now()}-${Math.random()}`;
}

function getSpeechRecognition(): SpeechRecognitionCtor | null {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

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
  return SENSITIVE_ACTIONS.has(action) && /lock|cover|garage|alarm|security|camera/.test(domain);
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
  if (policy && typeof policy.requires_review === "boolean") return policy.requires_review;
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
  return calls.map((c: any) => `${c.domain}.${c.service} ${c.data?.entity_id || ""}`.trim()).join(", ");
}

function outcomeLabel(command?: CommandResponse) {
  const outcome = command?.data?.outcome;
  if (!outcome) return "";
  if (!outcome.checked) return `Not checked: ${outcome.reason || "no verification needed"}`;
  return outcome.verified ? "Verified in Home Assistant" : "Needs review: state did not match";
}

function targetSummary(command?: CommandResponse) {
  const r = command?.resolved || {};
  return r.label || r.target || r.entity_id || r.door || r.routine || r.trigger?.platform || "";
}

function draftId(command?: CommandResponse) {
  const value = command?.data?.draft_id || command?.resolved?.draft_id;
  return typeof value === "number" ? value : undefined;
}

function commandFromLog(row: any): CommandResponse | undefined {
  if (!row?.intent || row.intent === "conversation") return undefined;
  return {
    success: row.success,
    assistant: row.assistant,
    user: row.user,
    conversation_id: row.conversation_id,
    intent: row.intent,
    resolved: row.resolved || {},
    executed: row.executed,
    requires_confirmation: false,
    message: row.response || "",
    tool_call: row.tool_call || {},
    data: row.data || {},
    error: row.error || "",
  };
}

function transcriptMessages(detail: any): Msg[] {
  const rows = detail?.messages || [];
  return rows.flatMap((row: any) => {
    const out: Msg[] = [];
    if (row.message) out.push({ id: `${row.id}-u`, role: "user", text: row.message });
    if (row.response) {
      out.push({
        id: `${row.id}-a`,
        role: "assistant",
        text: row.response,
        mode: row.intent === "conversation" ? "conversation" : row.intent,
        command: commandFromLog(row),
      });
    }
    return out;
  });
}

export default function Chat() {
  const [conversationId, setConversationId] = useState(() => id());
  const [activeTab, setActiveTab] = useState<"chat" | "notebook">("chat");
  const [session, setSession] = useState<any>(null);
  const [config, setConfig] = useState<any>(null);
  const [assistant, setAssistant] = useState("atlas");
  const [user, setUser] = useState("shawn");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [conversations, setConversations] = useState<any[]>([]);
  const [detail, setDetail] = useState<any>(null);
  const [note, setNote] = useState({ title: "Session note", body: "" });
  const [error, setError] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const [speakResponses, setSpeakResponses] = useState(false);
  const [safePreview] = useState(true);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const recognitionRef = useRef<InstanceType<SpeechRecognitionCtor> | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const speechSupported = useMemo(() => Boolean(getSpeechRecognition()), []);
  const users = session?.users || config?.assistants?.users || [];
  const assistants = session?.assistants || config?.assistants?.assistants || [];
  const selectedAssistant = assistants.find((a: any) => a.id === assistant);
  const selectedUser = users.find((u: any) => u.id === user);

  const refreshConversations = async (assistantId = assistant, userId = user) => {
    if (!assistantId || !userId) return;
    const response = await api.conversations(80, { assistant: assistantId, user: userId });
    setConversations(response.conversations || []);
  };

  const loadConversation = async (targetId: string) => {
    setBusy(true);
    setError(null);
    try {
      const response = await api.conversation(targetId);
      setConversationId(targetId);
      setDetail(response);
      setMessages(transcriptMessages(response));
      setActiveTab("chat");
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const newChat = () => {
    setConversationId(id());
    setMessages([]);
    setDetail(null);
    setActiveTab("chat");
  };

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
        void refreshConversations(defaultAssistant, defaultUser);
      })
      .catch(() => {
        /* keep safe starter defaults */
      });
  }, []);

  useEffect(() => {
    if (activeTab !== "notebook" || !conversationId) return;
    api.conversation(conversationId)
      .then(setDetail)
      .catch(() => {
        /* The current chat may not have been saved yet. */
      });
  }, [activeTab, conversationId, messages.length]);

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
      const response = await api.voiceSpeak({ assistant, text: message, reply_mode: "auto" });
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
    if (appendUser) setMessages((m) => [...m, { id: id(), role: "user", text: message }]);
    const r = await api.chat(assistant, user, message, conversationId);
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
    void refreshConversations();
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
        const preview = await api.chatPreview(assistant, user, message, conversationId);
        const command = preview.command as CommandResponse | undefined;
        if (shouldPauseForReview(command)) {
          const response = preview.response || command?.message || "Preview ready.";
          appendAssistant({ text: response, mode: preview.mode, kind: "preview", command, originalText: message });
          void speak(response);
          return;
        }
      }
      await executeChat(message, false);
    } catch (e: any) {
      setError(e.message || String(e));
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
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const installDraft = async (idToInstall: number) => {
    setBusy(true);
    setError(null);
    try {
      const result = await api.approveDraft(idToInstall);
      appendAssistant({
        text: result.message || "Automation installed in Home Assistant.",
        mode: result.installed ? "installed" : "approval",
      });
      void refreshConversations();
    } catch (e: any) {
      setError(e.message || String(e));
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
      appendAssistant({ text: r.message || "Confirmed.", mode: r.executed ? "confirmed" : "confirmation", command: r });
      void speak(r.message || "Confirmed.");
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async (token: string) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.cancelConfirm(token);
      appendAssistant({ text: r.message || "Cancelled.", mode: "cancelled", command: r });
      void speak(r.message || "Cancelled.");
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const addNote = async () => {
    if (!conversationId || !note.body.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.addConversationNote(conversationId, {
        title: note.title,
        body: note.body,
        assistant,
        user,
        source: "chat",
      });
      setNote({ title: "Session note", body: "" });
      const response = await api.conversation(conversationId);
      setDetail(response);
      void refreshConversations();
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const exportMarkdown = async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await api.exportConversation(conversationId);
      const blob = new Blob([response.markdown || ""], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = response.filename || `tpg-homeai-${conversationId}.md`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setError(e.message || String(e));
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
        if (event.results[i].isFinal) finalTranscript += transcript;
        else interimTranscript += transcript;
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
      if (transcript) void send(transcript);
    };
    setListening(true);
    recognition.start();
  };

  return (
    <div className="grid min-h-[calc(100vh-7rem)] gap-4 xl:grid-cols-[19rem_minmax(0,1fr)]">
      <aside className="card flex max-h-[calc(100vh-8rem)] min-h-[18rem] flex-col overflow-hidden p-3">
        <div className="mb-3 flex items-center gap-2">
          <Button className="min-h-10 flex-1 px-3 py-2 text-sm" onClick={newChat}>New chat</Button>
          <Button
            variant="ghost"
            className="min-h-10 px-3 py-2 text-sm"
            onClick={() => setSpeakResponses((v) => !v)}
            title="Toggle spoken replies"
          >
            {speakResponses ? "Voice on" : "Voice off"}
          </Button>
        </div>
        <div className="mb-3 grid grid-cols-2 gap-2">
          <button
            className={`rounded-lg border px-3 py-2 text-sm ${activeTab === "chat" ? "border-sky-400/50 bg-sky-400/15 text-sky-100" : "border-slate-800 bg-slate-950/30 text-slate-300"}`}
            onClick={() => setActiveTab("chat")}
          >
            Chat
          </button>
          <button
            className={`rounded-lg border px-3 py-2 text-sm ${activeTab === "notebook" ? "border-sky-400/50 bg-sky-400/15 text-sky-100" : "border-slate-800 bg-slate-950/30 text-slate-300"}`}
            onClick={() => setActiveTab("notebook")}
          >
            Notebook
          </button>
        </div>
        <div className="mb-3 rounded-xl border border-slate-800 bg-slate-950/35 p-3">
          <div className="text-sm font-semibold text-slate-100">{selectedAssistant?.name || assistant}</div>
          <div className="mt-1 text-xs text-slate-500">{selectedUser?.name || user} · {session?.role || "profile"}</div>
        </div>
        <div className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Conversations</div>
        <div className="min-h-0 flex-1 space-y-2 overflow-auto pr-1">
          {conversations.map((item) => (
            <button
              key={item.conversation_id}
              className={`w-full rounded-xl border px-3 py-2 text-left text-sm transition ${
                item.conversation_id === conversationId
                  ? "border-sky-400/50 bg-sky-400/15 text-slate-100"
                  : "border-slate-800 bg-slate-950/35 text-slate-300 hover:border-slate-600"
              }`}
              onClick={() => void loadConversation(item.conversation_id)}
            >
              <div className="line-clamp-2 font-medium">{item.title}</div>
              <div className="mt-1 text-xs text-slate-500">{item.message_count} messages · {item.note_count} notes</div>
            </button>
          ))}
          {conversations.length === 0 && <div className="rounded-xl border border-slate-800 bg-slate-950/30 p-3 text-sm text-slate-500">No saved chats yet.</div>}
        </div>
      </aside>

      <main className="flex min-h-[calc(100vh-8rem)] min-w-0 flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/35">
        <div className="flex min-h-16 items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
          <div className="min-w-0">
            <div className="truncate text-lg font-bold text-slate-100">{selectedAssistant?.name || "TPG AI"}</div>
            <div className="truncate text-xs text-slate-500">Signed in as {selectedUser?.name || "current HA user"}</div>
          </div>
          <div className="flex items-center gap-2">
            <button
              className={`btn-ghost min-h-10 px-3 py-2 text-sm ${listening ? "border-rose-400 bg-rose-500/20 text-rose-100" : ""}`}
              onClick={toggleListening}
              disabled={busy || !speechSupported}
              title={speechSupported ? "Use microphone" : "Voice input is not supported in this browser"}
            >
              {listening ? "Stop" : "Mic"}
            </button>
          </div>
        </div>

        {error && <div className="mx-4 mt-4 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}
        {voiceError && <div className="mx-4 mt-4 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-amber-100">{voiceError}</div>}

        {activeTab === "notebook" ? (
          <NotebookPanel
            detail={detail}
            conversationId={conversationId}
            note={note}
            setNote={setNote}
            addNote={addNote}
            exportMarkdown={exportMarkdown}
            busy={busy}
          />
        ) : (
          <>
            <section className="min-h-0 flex-1 space-y-5 overflow-auto px-4 py-6">
              {messages.length === 0 && (
                <div className="mx-auto flex min-h-[22rem] max-w-3xl flex-col items-center justify-center text-center">
                  <div className="text-2xl font-semibold text-slate-100">What do you want to do?</div>
                  <div className="mt-3 max-w-xl text-sm leading-relaxed text-slate-400">
                    Ask anything, brainstorm, control devices, or create a scheduled task like “turn off all lights at 10PM.”
                  </div>
                </div>
              )}
              {messages.map((m) => {
                const automationDraftId = draftId(m.command);
                return (
                  <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[min(48rem,92%)] rounded-2xl border px-4 py-3 text-sm shadow-lg ${
                      m.role === "user"
                        ? "border-sky-400/30 bg-sky-500/20 text-slate-50"
                        : m.kind === "preview"
                          ? "border-cyan-400/50 bg-cyan-950/45 text-slate-100"
                          : "border-slate-700 bg-slate-950/62 text-slate-200"
                    }`}>
                      {m.mode && <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-sky-300">{m.mode}</div>}
                      <div className="whitespace-pre-wrap break-words leading-relaxed">{m.text}</div>

                      {m.command && (
                        <div className="mt-3 space-y-2 rounded-xl border border-slate-700/70 bg-slate-950/50 p-3 text-xs text-slate-300">
                          <div className="flex flex-wrap gap-2">
                            {m.command.intent && <Badge tone="brand">{m.command.intent}</Badge>}
                            {m.command.data?.policy?.decision && <Badge>{m.command.data.policy.decision}</Badge>}
                            {m.command.requires_confirmation && <Badge tone="warn">confirmation</Badge>}
                            {automationDraftId && <Badge tone="warn">draft {automationDraftId}</Badge>}
                          </div>
                          <div className="grid gap-1">
                            {targetSummary(m.command) && <div><span className="text-slate-500">Target:</span> {targetSummary(m.command)}</div>}
                            {serviceSummary(m.command) && <div><span className="text-slate-500">Service:</span> {serviceSummary(m.command)}</div>}
                          </div>
                          {outcomeLabel(m.command) && (
                            <div className={m.command.data?.outcome?.verified === false ? "text-amber-200" : "text-emerald-200"}>
                              <span className="text-slate-500">Outcome:</span> {outcomeLabel(m.command)}
                            </div>
                          )}
                          {m.command.data?.security?.pin_required && <div className="text-amber-200">Security PIN required</div>}
                          <DeveloperDetails data={{ tool_call: m.command.tool_call, resolved: m.command.resolved, data: m.command.data }} />
                        </div>
                      )}

                      {m.kind === "preview" && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          <Button className="px-3 py-1.5 text-xs" onClick={() => void executePreview(m)} disabled={busy}>
                            {m.command?.requires_confirmation ? "Request confirmation" : PROPOSAL_INTENTS.has(m.command?.intent || "") ? "Create draft" : "Execute"}
                          </Button>
                          <Button variant="ghost" className="px-3 py-1.5 text-xs" onClick={() => appendAssistant({ text: "Cancelled.", mode: "cancelled" })} disabled={busy}>
                            Cancel
                          </Button>
                        </div>
                      )}

                      {automationDraftId && m.kind !== "preview" && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          <Button className="px-3 py-1.5 text-xs" onClick={() => void installDraft(automationDraftId)} disabled={busy}>
                            Install in HA
                          </Button>
                        </div>
                      )}

                      {m.kind === "confirmation" && m.command?.confirmation_token && (
                        <div className="mt-3 rounded-xl border border-amber-400/40 bg-amber-500/10 p-3">
                          <div className="font-semibold text-amber-100">Confirm action</div>
                          <div className="mt-1 text-xs text-amber-100/80">Review the target and confirm only if it is correct.</div>
                          <div className="mt-3 flex flex-wrap gap-2">
                            <Button variant="warning" className="px-3 py-1.5 text-xs" onClick={() => void confirm(m.command!.confirmation_token!)} disabled={busy}>
                              Confirm
                            </Button>
                            <Button variant="ghost" className="px-3 py-1.5 text-xs" onClick={() => void cancel(m.command!.confirmation_token!)} disabled={busy}>
                              Cancel
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </section>

            <div className="border-t border-slate-800 bg-slate-950/65 p-3">
              <div className="flex gap-2">
                <textarea
                  className="input min-h-[3.5rem] flex-1 resize-none rounded-2xl"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                  placeholder={listening ? "Listening..." : "Message TPG HomeAI..."}
                />
                <Button className="self-stretch rounded-2xl px-5" onClick={() => void send()} disabled={busy}>
                  {busy ? "Thinking..." : "Send"}
                </Button>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function NotebookPanel({
  detail,
  conversationId,
  note,
  setNote,
  addNote,
  exportMarkdown,
  busy,
}: {
  detail: any;
  conversationId: string;
  note: { title: string; body: string };
  setNote: (note: { title: string; body: string }) => void;
  addNote: () => void;
  exportMarkdown: () => void;
  busy: boolean;
}) {
  return (
    <section className="min-h-0 flex-1 overflow-auto p-4">
      <div className="mx-auto max-w-4xl space-y-4">
        <div className="rounded-2xl border border-slate-800 bg-slate-950/35 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-lg font-semibold text-slate-100">{detail?.messages?.[0]?.message || "Current conversation"}</div>
              <div className="mt-1 text-xs text-slate-500">{conversationId}</div>
            </div>
            <Button onClick={() => void exportMarkdown()} disabled={busy || !detail?.messages?.length}>Download Markdown</Button>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-950/35 p-4">
          <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Transcript</div>
          <div className="max-h-[28rem] space-y-3 overflow-auto pr-1">
            {(detail?.messages || []).map((message: any) => (
              <div key={message.id} className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
                <div className="mb-2 text-xs text-slate-500">{message.created_at}</div>
                <div className="mb-2 text-sm text-slate-200"><span className="text-slate-500">User:</span> {message.message}</div>
                <div className="whitespace-pre-wrap text-sm text-slate-300"><span className="text-slate-500">Assistant:</span> {message.response}</div>
              </div>
            ))}
            {(!detail?.messages || detail.messages.length === 0) && <div className="text-sm text-slate-500">No transcript loaded yet.</div>}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-950/35 p-4">
          <div className="mb-3 text-lg font-semibold text-slate-100">Notes</div>
          <div className="mb-4 space-y-2">
            {(detail?.notes || []).map((n: any) => (
              <div key={n.id} className="rounded-xl border border-slate-800 bg-slate-950/50 p-3">
                <div className="text-sm font-semibold text-slate-200">{n.title}</div>
                <div className="mt-1 whitespace-pre-wrap text-sm text-slate-400">{n.body}</div>
              </div>
            ))}
            {(!detail?.notes || detail.notes.length === 0) && <div className="text-sm text-slate-500">No notes attached.</div>}
          </div>
          <input className="input mb-2" value={note.title} onChange={(e) => setNote({ ...note, title: e.target.value })} />
          <textarea className="input min-h-24" value={note.body} onChange={(e) => setNote({ ...note, body: e.target.value })} placeholder="Add a note to this conversation..." />
          <div className="mt-3">
            <Button onClick={() => void addNote()} disabled={busy || !note.body.trim()}>Add note</Button>
          </div>
        </div>
      </div>
    </section>
  );
}
