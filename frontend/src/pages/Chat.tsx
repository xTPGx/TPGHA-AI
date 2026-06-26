import type { UIEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, CommandResponse } from "../api";
import Badge from "../components/Badge";
import Button from "../components/Button";
import DeveloperDetails from "../components/DeveloperDetails";
import { homeAssistantSessionHints, startHomeAssistantUserBridge } from "../haAuth";

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

type MicState = "idle" | "recording" | "transcribing";

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 6h18" />
      <path d="M8 6V4h8v2" />
      <path d="M19 6l-1 14H6L5 6" />
      <path d="M10 11v5" />
      <path d="M14 11v5" />
    </svg>
  );
}

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

function readPanelMode(): boolean {
  try {
    return localStorage.getItem("tpg.panelMode") === "1";
  } catch {
    return false;
  }
}

// Returns the command text following a wake word, or "" if no wake word was
// heard. "Jarvis, turn off the office light" -> "turn off the office light".
function extractCommandAfterWakeWord(heard: string, wakeWords: string[]): string {
  const lower = heard.toLowerCase();
  for (const word of wakeWords) {
    if (!word) continue;
    const idx = lower.indexOf(word);
    if (idx === -1) continue;
    const rest = heard.slice(idx + word.length).replace(/^[\s,.:!?-]+/, "").trim();
    return rest;
  }
  return "";
}

function getPreferredAudioMimeType() {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") return "";
  return [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/aac",
    "audio/mpeg",
  ].find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

function microphoneUnavailableMessage() {
  const secureEnough = window.isSecureContext || ["localhost", "127.0.0.1"].includes(window.location.hostname);
  if (!secureEnough) {
    return "Microphone capture is blocked because Home Assistant is open over HTTP. Use HTTPS for Home Assistant (Nabu Casa, Tailscale HTTPS, Cloudflare, or a local trusted cert). Localhost only works on the device running the browser.";
  }
  return "Microphone capture is not available in this browser. Use the Home Assistant app/browser microphone permission, or try HTTPS.";
}

function microphoneErrorMessage(error: any) {
  const name = String(error?.name || error?.error || "").toLowerCase();
  const message = String(error?.message || "");
  const host = window.location.hostname;
  const localHost = ["localhost", "127.0.0.1", "::1"].includes(host);
  const secureEnough = window.isSecureContext || localHost;
  if (!secureEnough) {
    return [
      "Microphone blocked: Home Assistant is being served over HTTP.",
      "Browsers require HTTPS for microphone capture unless the page is opened on localhost.",
      "On your iPad/iPhone, localhost would mean the iPad/iPhone itself, not the HA server.",
      "Fix: use Nabu Casa remote UI, Tailscale HTTPS, Cloudflare Tunnel, or a local trusted HTTPS certificate for Home Assistant.",
    ].join(" ");
  }
  if (name.includes("notallowed") || name.includes("not-allowed") || name.includes("security")) {
    return [
      "Microphone blocked by permission.",
      "Allow microphone access for the Home Assistant app/browser and this HA site.",
      "On iPhone/iPad: Settings > Home Assistant > Microphone, then fully close and reopen the app.",
    ].join(" ");
  }
  if (name.includes("notfound") || name.includes("not-found") || name.includes("devicesnotfound")) {
    return "No microphone was found on this device. Check OS microphone settings or try another browser/device.";
  }
  if (name.includes("notreadable") || name.includes("trackstart")) {
    return "The microphone is already in use or unavailable. Close other voice/camera apps and try again.";
  }
  if (name.includes("abort")) {
    return "Microphone capture was interrupted before audio was recorded. Try again and keep the page open.";
  }
  return message ? `Microphone recording failed: ${message}` : microphoneUnavailableMessage();
}

async function microphoneReadinessReport() {
  const host = window.location.hostname;
  const localHost = ["localhost", "127.0.0.1", "::1"].includes(host);
  const secureEnough = window.isSecureContext || localHost;
  const recorder = Boolean(typeof navigator.mediaDevices?.getUserMedia === "function" && typeof MediaRecorder !== "undefined");
  const speech = Boolean(getSpeechRecognition());
  let permission = "unknown";
  try {
    const permissions = (navigator as any).permissions;
    if (permissions?.query) {
      const result = await permissions.query({ name: "microphone" as PermissionName });
      permission = result?.state || "unknown";
    }
  } catch {
    permission = "unknown";
  }
  const lines = [
    `Voice environment: ${secureEnough ? "secure enough" : "HTTP/insecure"}.`,
    `Host: ${host}${localHost ? " (browser-local only)" : ""}.`,
    `Recorder API: ${recorder ? "available" : "missing"}.`,
    `Speech API: ${speech ? "available" : "missing"}.`,
    `Browser permission: ${permission}.`,
  ];
  if (!secureEnough) {
    lines.push("Use HTTPS for HA. Localhost cannot help an iPad unless HA is running on that iPad.");
  } else if (permission === "denied") {
    lines.push("Reset microphone permission in the Home Assistant app or browser site settings.");
  } else if (!recorder && !speech) {
    lines.push("This browser cannot capture microphone input for TPG HomeAI.");
  } else {
    lines.push("If the next attempt fails, it is likely an OS/app permission or another app holding the mic.");
  }
  return lines.join(" ");
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

function quickPrompt(text: string) {
  return text;
}

// Minimal, dependency-free markdown for assistant messages: fenced code
// blocks, bullet/numbered lists, and inline bold/italic/code. Renders to React
// nodes (no dangerouslySetInnerHTML) so it stays XSS-safe.
function renderInline(text: string, keyBase: string): (string | JSX.Element)[] {
  const nodes: (string | JSX.Element)[] = [];
  const regex = /(\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const key = `${keyBase}-i${i++}`;
    if (match[2] !== undefined) nodes.push(<strong key={key}>{match[2]}</strong>);
    else if (match[3] !== undefined) nodes.push(<em key={key}>{match[3]}</em>);
    else if (match[4] !== undefined) nodes.push(<code key={key} className="rounded bg-black/40 px-1 py-0.5 text-[0.85em]">{match[4]}</code>);
    last = regex.lastIndex;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function Markdown({ text }: { text: string }) {
  const lines = (text || "").split("\n");
  const blocks: JSX.Element[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim().startsWith("```")) {
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1;
      blocks.push(
        <pre key={`b${key++}`} className="code-scroll my-2 whitespace-pre-wrap">{code.join("\n")}</pre>,
      );
      continue;
    }
    if (/^\s*([-*])\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*])\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*])\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ul key={`b${key++}`} className="my-1 list-disc space-y-1 pl-5">
          {items.map((it, n) => <li key={n}>{renderInline(it, `${key}-${n}`)}</li>)}
        </ul>,
      );
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ""));
        i += 1;
      }
      blocks.push(
        <ol key={`b${key++}`} className="my-1 list-decimal space-y-1 pl-5">
          {items.map((it, n) => <li key={n}>{renderInline(it, `${key}-${n}`)}</li>)}
        </ol>,
      );
      continue;
    }
    if (line.trim() === "") {
      i += 1;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() !== "" && !lines[i].trim().startsWith("```") && !/^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
      para.push(lines[i]);
      i += 1;
    }
    blocks.push(
      <p key={`b${key++}`} className="whitespace-pre-wrap break-words leading-relaxed">
        {renderInline(para.join("\n"), `${key}`)}
      </p>,
    );
  }
  return <div className="space-y-2 text-sm">{blocks}</div>;
}

export default function Chat() {
  const [conversationId, setConversationId] = useState(() => id());
  const [activeTab, setActiveTab] = useState<"chat" | "notebook">("chat");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [session, setSession] = useState<any>(null);
  const [config, setConfig] = useState<any>(null);
  const [assistant, setAssistant] = useState("jarvis");
  const [user, setUser] = useState("house_remote");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [conversations, setConversations] = useState<any[]>([]);
  const [detail, setDetail] = useState<any>(null);
  const [note, setNote] = useState({ title: "Session note", body: "" });
  const [error, setError] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const [micState, setMicState] = useState<MicState>("idle");
  const [speakResponses, setSpeakResponses] = useState(false);
  const [safePreview] = useState(true);
  const [actionPolicy, setActionPolicy] = useState<any>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [lastTranscript, setLastTranscript] = useState("");
  const [panelMode, setPanelMode] = useState(() => readPanelMode());
  const [panelListening, setPanelListening] = useState(false);
  const [panelHeard, setPanelHeard] = useState("");
  const [panelRoom, setPanelRoom] = useState(() => localStorage.getItem("tpg.panelRoom") || "");
  const panelRecognitionRef = useRef<InstanceType<SpeechRecognitionCtor> | null>(null);
  const sendRef = useRef<(override?: string, room?: string) => void>(() => {});
  const recognitionRef = useRef<InstanceType<SpeechRecognitionCtor> | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const mediaChunksRef = useRef<Blob[]>([]);
  const discardRecordingRef = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const forceScrollRef = useRef(false);
  const [stuckToBottom, setStuckToBottom] = useState(true);
  const speechSupported = useMemo(() => Boolean(getSpeechRecognition()), []);
  const recorderSupported = useMemo(
    () => Boolean(typeof navigator.mediaDevices?.getUserMedia === "function" && typeof MediaRecorder !== "undefined"),
    [],
  );
  const users = session?.users || config?.assistants?.users || [];
  const assistants = session?.assistants || config?.assistants?.assistants || [];
  const selectedAssistant = assistants.find((a: any) => a.id === assistant);
  const selectedUser = users.find((u: any) => u.id === user);
  const wakeWords = useMemo(() => {
    const configured = (selectedAssistant?.wake_words || []) as string[];
    const base = configured.length ? configured : ["jarvis", "atlas", "chatty", "hey jarvis", "computer"];
    return base.map((w) => String(w || "").trim().toLowerCase()).filter(Boolean);
  }, [selectedAssistant]);

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
      forceScrollRef.current = true;
      setConversationId(targetId);
      setDetail(response);
      setMessages(transcriptMessages(response));
      setActiveTab("chat");
      setHistoryOpen(false);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const newChat = () => {
    forceScrollRef.current = true;
    setConversationId(id());
    setMessages([]);
    setDetail(null);
    setActiveTab("chat");
    setHistoryOpen(false);
  };

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
      try {
        panelRecognitionRef.current?.stop();
      } catch {
        /* ignore */
      }
      if (mediaRecorderRef.current?.state === "recording") mediaRecorderRef.current.stop();
      mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
      audioRef.current?.pause();
      window.speechSynthesis?.cancel();
    };
  }, []);

  useEffect(() => {
    if (!forceScrollRef.current && !stickToBottomRef.current) return;
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    forceScrollRef.current = false;
  }, [messages, busy]);

  useEffect(() => {
    if (micState !== "recording") {
      setRecordingSeconds(0);
      return;
    }
    setRecordingSeconds(0);
    const timer = window.setInterval(() => setRecordingSeconds((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [micState]);

  const handleChatScroll = (event: UIEvent<HTMLElement>) => {
    const el = event.currentTarget;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    stickToBottomRef.current = nearBottom;
    setStuckToBottom(nearBottom);
  };

  const jumpToLatest = () => {
    stickToBottomRef.current = true;
    forceScrollRef.current = true;
    setStuckToBottom(true);
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  };

  useEffect(() => {
    let cancelled = false;
    const applySession = (sessionResult: any, configResult = config) => {
      if (cancelled) return;
      setSession(sessionResult);
      if (configResult) setConfig(configResult);
      const defaultUser = (
        sessionResult.detected_user?.id ||
        configResult?.assistants?.users?.find((u: any) => u.role === "kiosk")?.id ||
        configResult?.assistants?.users?.[0]?.id ||
        "house_remote"
      );
      const defaultAssistant = (
        sessionResult.default_assistant?.id ||
        configResult?.assistants?.assistants?.find((a: any) => a.owner === defaultUser)?.id ||
        configResult?.assistants?.assistants?.[0]?.id ||
        "jarvis"
      );
      setUser(defaultUser);
      setAssistant(defaultAssistant);
      void refreshConversations(defaultAssistant, defaultUser);
    };
    Promise.all([api.uiSession(homeAssistantSessionHints()), api.config()])
      .then(([sessionResult, configResult]) => {
        applySession(sessionResult, configResult);
      })
      .catch(() => {
        /* keep safe starter defaults */
      });
    const stopBridge = startHomeAssistantUserBridge((bridgeUser) => {
      api.uiSession({ accessToken: homeAssistantSessionHints().accessToken, clientUser: bridgeUser })
        .then((sessionResult) => applySession(sessionResult))
        .catch(() => {
          /* keep current session */
        });
    });
    return () => {
      cancelled = true;
      stopBridge();
    };
  }, []);

  useEffect(() => {
    const role = session?.role || "guest";
    let cancelled = false;
    api.roleActionPolicy(role)
      .then((policy) => {
        if (!cancelled) setActionPolicy(policy);
      })
      .catch(() => {
        if (!cancelled) setActionPolicy(null);
      });
    return () => {
      cancelled = true;
    };
  }, [session?.role]);

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

  const executeChat = async (message: string, appendUser = false, room = panelRoom) => {
    if (appendUser) setMessages((m) => [...m, { id: id(), role: "user", text: message }]);
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
    void refreshConversations();
  };

  const send = async (override?: string, room = panelRoom) => {
    const message = (override ?? text).trim();
    if (!message) return;
    setText("");
    setBusy(true);
    setError(null);
    forceScrollRef.current = true;
    setMessages((m) => [...m, { id: id(), role: "user", text: message }]);
    try {
      if (safePreview) {
        const preview = await api.chatPreview(assistant, user, message, conversationId, room || undefined);
        const command = preview.command as CommandResponse | undefined;
        if (shouldPauseForReview(command)) {
          const response = preview.response || command?.message || "Preview ready.";
          appendAssistant({ text: response, mode: preview.mode, kind: "preview", command, originalText: message });
          void speak(response);
          return;
        }
      }
      await executeChat(message, false, room);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  sendRef.current = (override?: string, room?: string) => void send(override, room);

  const deleteConversation = async (targetId: string) => {
    if (!targetId) return;
    const item = conversations.find((c) => c.conversation_id === targetId);
    const title = item?.title || "this conversation";
    if (!window.confirm(`Remove "${title}" from recent chats? Audit history will be preserved.`)) return;
    const previous = conversations;
    setConversations((current) => current.filter((c) => c.conversation_id !== targetId));
    if (targetId === conversationId) newChat();
    try {
      await api.deleteConversation(targetId);
    } catch (e: any) {
      setConversations(previous);
      setError(e.message || String(e));
    }
  };

  useEffect(() => {
    localStorage.setItem("tpg.panelMode", panelMode ? "1" : "0");
  }, [panelMode]);

  useEffect(() => {
    localStorage.setItem("tpg.panelRoom", panelRoom);
  }, [panelRoom]);

  // Always-listening panel mode: a continuous recognizer listens for the
  // assistant's wake word and forwards the rest of the phrase as a command.
  // Works on Chrome/Android; iOS Safari can't keep the mic open in the
  // background, so it stays on tap-to-talk (push-to-talk) instead.
  useEffect(() => {
    if (!panelMode) {
      setPanelListening(false);
      return;
    }
    const SpeechRecognition = getSpeechRecognition();
    if (!SpeechRecognition) {
      setVoiceError(
        "Always-listening panel mode needs the Web Speech API (Chrome/Android). On iPhone/iPad, use the Mic button (tap to talk).",
      );
      setPanelMode(false);
      return;
    }
    let stopped = false;
    const recognition = new SpeechRecognition();
    panelRecognitionRef.current = recognition;
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.lang = "en-US";
    recognition.onresult = (event: any) => {
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        if (!event.results[i].isFinal) continue;
        const heard = String(event.results[i][0].transcript || "").trim();
        if (!heard) continue;
        setPanelHeard(heard);
        const command = extractCommandAfterWakeWord(heard, wakeWords);
        if (command) sendRef.current(command, panelRoom);
      }
    };
    recognition.onerror = () => {
      /* transient (no-speech/aborted); onend restarts. */
    };
    recognition.onend = () => {
      if (!stopped && panelMode) {
        try {
          recognition.start();
        } catch {
          /* already started */
        }
      } else {
        setPanelListening(false);
      }
    };
    try {
      recognition.start();
      setPanelListening(true);
    } catch {
      /* ignore */
    }
    return () => {
      stopped = true;
      setPanelListening(false);
      try {
        recognition.stop();
      } catch {
        /* ignore */
      }
    };
  }, [panelMode, wakeWords.join("|"), panelRoom]);

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

  const stopRecorderTracks = () => {
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
  };

  const transcribeRecording = async (blob: Blob) => {
    if (blob.size < 64) {
      setVoiceError("I did not receive enough microphone audio. Try holding the button a little longer.");
      setMicState("idle");
      setListening(false);
      return;
    }
    setMicState("transcribing");
    setListening(false);
    try {
      const extension = blob.type.includes("mp4") || blob.type.includes("aac") ? "m4a" : "webm";
      const response = await api.voiceTranscribe(blob, `voice-input.${extension}`);
      const transcript = String(response.text || "").trim();
      if (!response.success || !transcript) {
        setVoiceError(response.error || "I could not understand the microphone recording.");
        return;
      }
      setLastTranscript(transcript);
      setText(transcript);
      await send(transcript);
    } catch (e: any) {
      setVoiceError(e.message || "Voice transcription failed.");
    } finally {
      setMicState("idle");
    }
  };

  const startRecorder = async () => {
    if (!recorderSupported) return false;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      mediaStreamRef.current = stream;
      mediaChunksRef.current = [];
      discardRecordingRef.current = false;
      const mimeType = getPreferredAudioMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data?.size) mediaChunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        stopRecorderTracks();
        setMicState("idle");
        setListening(false);
        setVoiceError("Microphone recording failed. Check microphone permission for Home Assistant.");
      };
      recorder.onstop = () => {
        if (discardRecordingRef.current) {
          discardRecordingRef.current = false;
          mediaChunksRef.current = [];
          stopRecorderTracks();
          setMicState("idle");
          setListening(false);
          return;
        }
        const type = recorder.mimeType || mimeType || "audio/webm";
        const blob = new Blob(mediaChunksRef.current, { type });
        stopRecorderTracks();
        void transcribeRecording(blob);
      };
      recorder.start();
      setMicState("recording");
      setListening(true);
      return true;
    } catch (e: any) {
      const name = String(e?.name || "");
      if (name === "NotAllowedError" || name === "SecurityError") {
        setVoiceError(microphoneErrorMessage(e));
        return true;
      }
      setVoiceError(microphoneErrorMessage(e));
      return true;
    }
  };

  const toggleListening = async () => {
    setVoiceError(null);
    if (micState === "recording") {
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      } else {
        recognitionRef.current?.stop();
      }
      setListening(false);
      return;
    }
    if (micState === "transcribing") return;

    discardRecordingRef.current = false;
    const recordingStarted = await startRecorder();
    if (recordingStarted) return;

    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }
    const SpeechRecognition = getSpeechRecognition();
    if (!SpeechRecognition) {
      setVoiceError(microphoneUnavailableMessage());
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
      setVoiceError(microphoneErrorMessage(event));
      setMicState("idle");
      setListening(false);
    };
    recognition.onend = () => {
      setMicState("idle");
      setListening(false);
      if (discardRecordingRef.current) {
        discardRecordingRef.current = false;
        return;
      }
      const transcript = finalTranscript.trim();
      if (transcript) {
        setLastTranscript(transcript);
        void send(transcript);
      }
    };
    setMicState("recording");
    setListening(true);
    recognition.start();
  };

  const cancelVoiceInput = () => {
    setVoiceError(null);
    discardRecordingRef.current = true;
    try {
      if (mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      }
    } catch {
      /* ignore */
    }
    try {
      recognitionRef.current?.stop();
    } catch {
      /* ignore */
    }
    mediaChunksRef.current = [];
    stopRecorderTracks();
    setListening(false);
    setMicState("idle");
  };

  const sidebar = (
    <ConversationRail
      activeTab={activeTab}
      setActiveTab={setActiveTab}
      conversations={conversations}
      conversationId={conversationId}
      selectedAssistant={selectedAssistant}
      selectedUser={selectedUser}
      sessionRole={session?.role || "profile"}
      actionPolicy={actionPolicy}
      speakResponses={speakResponses}
      setSpeakResponses={setSpeakResponses}
      newChat={newChat}
      loadConversation={loadConversation}
      deleteConversation={deleteConversation}
      close={() => setHistoryOpen(false)}
    />
  );

  return (
    <div className="relative flex h-full min-h-0 bg-[#0a0a0a] text-slate-100">
      <aside className="hidden w-[18rem] shrink-0 border-r border-white/10 bg-[#0f0f0f] md:block">
        {sidebar}
      </aside>

      {historyOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <button className="absolute inset-0 bg-black/60" onClick={() => setHistoryOpen(false)} aria-label="Close chat history" />
          <aside className="relative h-full w-[min(21rem,88vw)] border-r border-white/10 bg-[#0f0f0f] shadow-2xl">
            {sidebar}
          </aside>
        </div>
      )}

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-white/10 bg-[#0a0a0a]/95 px-3 backdrop-blur sm:px-5">
          <div className="flex min-w-0 items-center gap-3">
            <button className="chat-icon-btn md:hidden" onClick={() => setHistoryOpen(true)} aria-label="Open chat history">
              <span className="block h-0.5 w-5 rounded bg-current" />
              <span className="block h-0.5 w-5 rounded bg-current" />
              <span className="block h-0.5 w-5 rounded bg-current" />
            </button>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-slate-100 sm:text-base">{selectedAssistant?.name || "TPG HomeAI"}</div>
              <div className="truncate text-xs text-slate-500">{selectedUser?.name || "Home Assistant user"} profile</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              className={`chat-pill ${activeTab === "notebook" ? "border-white/25 bg-white/10 text-white" : ""}`}
              onClick={() => setActiveTab(activeTab === "notebook" ? "chat" : "notebook")}
            >
              {activeTab === "notebook" ? "Chat" : "Notes"}
            </button>
            {speechSupported && (
              <button
                className={`chat-pill ${panelMode ? "border-emerald-400/50 bg-emerald-400/15 text-emerald-100" : ""}`}
                onClick={() => setPanelMode(!panelMode)}
                title="Always-listening panel mode (say the wake word)"
              >
                {panelMode ? "Panel on" : "Panel"}
              </button>
            )}
            <button
              className={`chat-icon-btn ${listening ? "border-rose-400/60 bg-rose-500/20 text-rose-100" : ""}`}
              onClick={() => void toggleListening()}
              disabled={busy || micState === "transcribing"}
              title={recorderSupported || speechSupported ? "Use microphone" : "Check microphone availability"}
              aria-label="Use microphone"
            >
              {micState === "recording" ? "Stop" : micState === "transcribing" ? "..." : "Mic"}
            </button>
          </div>
        </header>

        {error && <div className="mx-4 mt-4 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}
        {voiceError && (
          <div className="mx-4 mt-4 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-100">
            <div>{voiceError}</div>
            <button
              className="mt-3 rounded-lg border border-amber-300/30 px-3 py-1.5 text-xs font-semibold text-amber-50 hover:bg-amber-300/10"
              onClick={async () => setVoiceError(await microphoneReadinessReport())}
            >
              Diagnose mic
            </button>
          </div>
        )}
        {(micState !== "idle" || lastTranscript) && (
          <VoiceSessionBar
            micState={micState}
            listening={listening}
            recordingSeconds={recordingSeconds}
            lastTranscript={lastTranscript}
            cancelVoiceInput={cancelVoiceInput}
          />
        )}

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
            <section className="relative min-h-0 flex-1 overflow-y-auto px-3 py-6 sm:px-6" onScroll={handleChatScroll}>
              <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col">
                {messages.length === 0 && (
                  <EmptyState assistantName={selectedAssistant?.name || "TPG HomeAI"} onPrompt={(prompt) => void send(prompt)} />
                )}
                <div className="space-y-6">
                  {messages.map((m) => (
                    <MessageBubble
                      key={m.id}
                      message={m}
                      busy={busy}
                      executePreview={executePreview}
                      appendAssistant={appendAssistant}
                      installDraft={installDraft}
                      confirm={confirm}
                      cancel={cancel}
                    />
                  ))}
                  {busy && messages[messages.length - 1]?.role === "user" && (
                    <div className="flex justify-start">
                      <div className="chat-assistant-bubble flex items-center gap-1.5">
                        <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.2s]" />
                        <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400 [animation-delay:-0.1s]" />
                        <span className="h-2 w-2 animate-bounce rounded-full bg-slate-400" />
                      </div>
                    </div>
                  )}
                  <div ref={bottomRef} />
                </div>
              </div>
              {!stuckToBottom && (
                <button
                  className="fixed bottom-24 left-1/2 z-10 -translate-x-1/2 rounded-full border border-white/10 bg-[#171717] px-3 py-1.5 text-xs font-semibold text-slate-200 shadow-lg transition hover:border-white/25 hover:bg-[#222]"
                  onClick={jumpToLatest}
                >
                  Jump to latest
                </button>
              )}
            </section>

            <div className="shrink-0 border-t border-white/10 bg-[#0a0a0a]/95 px-3 py-3 backdrop-blur sm:px-6">
              {panelMode && (
                <div className="mx-auto mb-2 flex max-w-3xl flex-wrap items-center gap-2 text-xs">
                  <span className={`inline-flex h-2.5 w-2.5 rounded-full ${panelListening ? "animate-pulse bg-emerald-400" : "bg-slate-600"}`} />
                  <span className="text-slate-400">
                    {panelListening
                      ? `Listening for "${wakeWords[0] || "the wake word"}"…`
                      : "Panel mode paused"}
                  </span>
                  <input
                    className="ml-auto w-32 rounded-lg border border-white/10 bg-black/30 px-2 py-1 text-xs text-slate-200 outline-none placeholder:text-slate-600 focus:border-white/30"
                    value={panelRoom}
                    onChange={(e) => setPanelRoom(e.target.value)}
                    placeholder="Room (optional)"
                    title="Room context for hands-free commands"
                  />
                  {panelHeard && <span className="w-full truncate text-slate-500">heard: {panelHeard}</span>}
                </div>
              )}
              <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-white/10 bg-[#171717] p-2 shadow-[0_18px_50px_rgba(0,0,0,0.4)]">
                <button
                  className={`chat-icon-btn shrink-0 ${micState === "recording" ? "border-rose-400/60 bg-rose-500/20 text-rose-100" : ""}`}
                  onClick={() => void toggleListening()}
                  disabled={busy || micState === "transcribing"}
                  title={recorderSupported || speechSupported ? "Hold to talk" : "Check microphone availability"}
                  aria-label="Use microphone"
                >
                  {micState === "recording" ? "Stop" : micState === "transcribing" ? "..." : "Mic"}
                </button>
                <textarea
                  className="min-h-[3rem] flex-1 resize-none bg-transparent px-3 py-2 text-sm leading-relaxed text-slate-100 outline-none placeholder:text-slate-500"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                  placeholder={listening ? "Listening... tap Stop to send" : "Message TPG HomeAI"}
                />
                <button className="chat-send-btn" onClick={() => void send()} disabled={busy || !text.trim()}>
                  {busy ? "..." : "Send"}
                </button>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function VoiceSessionBar({
  micState,
  listening,
  recordingSeconds,
  lastTranscript,
  cancelVoiceInput,
}: {
  micState: MicState;
  listening: boolean;
  recordingSeconds: number;
  lastTranscript: string;
  cancelVoiceInput: () => void;
}) {
  const label = micState === "recording"
    ? `Listening ${recordingSeconds}s`
    : micState === "transcribing"
      ? "Transcribing"
      : "Last voice input";
  return (
    <div className="mx-4 mt-4 rounded-2xl border border-white/10 bg-[#111827]/80 p-3 text-sm text-slate-200">
      <div className="flex flex-wrap items-center gap-3">
        <span className={`h-2.5 w-2.5 rounded-full ${listening ? "animate-pulse bg-rose-400" : "bg-sky-400"}`} />
        <span className="font-semibold">{label}</span>
        {micState === "recording" && (
          <div className="flex items-end gap-1" aria-hidden="true">
            {[0, 1, 2, 3].map((bar) => (
              <span
                key={bar}
                className="w-1 rounded bg-sky-300/80"
                style={{ height: `${10 + ((recordingSeconds + bar) % 4) * 5}px` }}
              />
            ))}
          </div>
        )}
        {micState !== "idle" && (
          <button
            className="ml-auto rounded-lg border border-white/10 px-3 py-1.5 text-xs font-semibold text-slate-200 hover:border-rose-300/40 hover:bg-rose-500/10 hover:text-rose-100"
            onClick={cancelVoiceInput}
          >
            Cancel
          </button>
        )}
      </div>
      {lastTranscript && (
        <div className="mt-2 rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs text-slate-400">
          Heard: <span className="text-slate-200">{lastTranscript}</span>
        </div>
      )}
    </div>
  );
}

function ConversationRail({
  activeTab,
  setActiveTab,
  conversations,
  conversationId,
  selectedAssistant,
  selectedUser,
  sessionRole,
  actionPolicy,
  speakResponses,
  setSpeakResponses,
  newChat,
  loadConversation,
  deleteConversation,
  close,
}: {
  activeTab: "chat" | "notebook";
  setActiveTab: (tab: "chat" | "notebook") => void;
  conversations: any[];
  conversationId: string;
  selectedAssistant: any;
  selectedUser: any;
  sessionRole: string;
  actionPolicy: any;
  speakResponses: boolean;
  setSpeakResponses: (value: boolean) => void;
  newChat: () => void;
  loadConversation: (id: string) => Promise<void>;
  deleteConversation: (id: string) => Promise<void>;
  close: () => void;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col p-3">
      <div className="mb-3 flex items-center justify-between gap-2 md:hidden">
        <div className="text-sm font-semibold text-slate-100">Workspace</div>
        <button className="chat-pill" onClick={close}>Close</button>
      </div>
      <button className="mb-3 min-h-11 rounded-xl bg-white px-4 text-sm font-semibold text-black transition hover:bg-white/90" onClick={newChat}>
        New chat
      </button>
      <div className="mb-3 grid grid-cols-2 gap-1 rounded-xl border border-white/10 bg-black/20 p-1">
        <button
          className={`rounded-lg px-3 py-2 text-sm transition ${activeTab === "chat" ? "bg-white/10 text-white" : "text-slate-400 hover:text-slate-100"}`}
          onClick={() => setActiveTab("chat")}
        >
          Chat
        </button>
        <button
          className={`rounded-lg px-3 py-2 text-sm transition ${activeTab === "notebook" ? "bg-white/10 text-white" : "text-slate-400 hover:text-slate-100"}`}
          onClick={() => setActiveTab("notebook")}
        >
          Notes
        </button>
      </div>
      <div className="mb-4 rounded-xl border border-white/10 bg-white/[0.03] p-3">
        <div className="truncate text-sm font-semibold text-slate-100">{selectedAssistant?.name || "Assistant"}</div>
        <div className="mt-1 truncate text-xs text-slate-500">{selectedUser?.name || "HA user"} · {sessionRole}</div>
        <button
          className={`mt-3 w-full rounded-lg border px-3 py-2 text-xs font-semibold transition ${
            speakResponses
              ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-100"
              : "border-white/10 bg-black/20 text-slate-300"
          }`}
          onClick={() => setSpeakResponses(!speakResponses)}
        >
          {speakResponses ? "Voice replies on" : "Voice replies off"}
        </button>
      </div>
      <RolePolicyMini policy={actionPolicy} />
      <div className="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Recent chats</div>
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
        {conversations.map((item) => (
          <div
            key={item.conversation_id}
            className={`group flex w-full items-start gap-2 rounded-xl px-3 py-2.5 transition ${
              item.conversation_id === conversationId ? "bg-white/10 text-slate-100" : "text-slate-400 hover:bg-white/[0.06] hover:text-slate-100"
            }`}
          >
            <button
              className="min-w-0 flex-1 text-left"
              onClick={() => void loadConversation(item.conversation_id)}
            >
              <div className="line-clamp-2 text-sm font-medium leading-snug">{item.title}</div>
              <div className="mt-1 text-xs text-slate-600 group-hover:text-slate-500">{item.message_count} messages · {item.note_count} notes</div>
            </button>
            <button
              className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-transparent text-slate-500 opacity-0 transition hover:border-rose-400/30 hover:bg-rose-500/10 hover:text-rose-200 group-hover:opacity-100 focus:opacity-100"
              onClick={(event) => {
                event.stopPropagation();
                void deleteConversation(item.conversation_id);
              }}
              title="Remove from recent chats"
              aria-label={`Remove ${item.title || "conversation"} from recent chats`}
            >
              <TrashIcon />
            </button>
          </div>
        ))}
        {conversations.length === 0 && <div className="rounded-xl border border-white/10 bg-black/20 p-3 text-sm text-slate-500">No saved chats yet.</div>}
      </div>
    </div>
  );
}

function RolePolicyMini({ policy }: { policy: any }) {
  if (!policy?.highlights?.length) return null;
  return (
    <div className="mb-4 rounded-xl border border-white/10 bg-black/20 p-3">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">This login can</div>
      <div className="space-y-2">
        {policy.highlights.slice(0, 4).map((item: any) => (
          <div key={item.id || item.title} className="flex items-start gap-2 text-xs">
            <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${item.allowed ? "bg-emerald-400" : "bg-amber-400"}`} />
            <div className="min-w-0">
              <div className="truncate font-semibold text-slate-200">{item.title}</div>
              <div className="line-clamp-2 text-slate-500">{item.allowed ? item.detail : "Owner/admin only"}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function EmptyState({ assistantName, onPrompt }: { assistantName: string; onPrompt: (prompt: string) => void }) {
  const prompts = [
    "Create scheduled task. Turn off all lights at 10PM.",
    "What should I improve in my smart home?",
    "Build a dashboard for the office.",
    "What is the weather today?",
  ];
  return (
    <div className="flex flex-1 flex-col justify-center py-10">
      <div className="mb-8 text-center">
        <div className="text-3xl font-semibold tracking-tight text-slate-50 sm:text-4xl">{assistantName}</div>
        <div className="mx-auto mt-3 max-w-xl text-sm leading-relaxed text-slate-400">
          Ask anything, brainstorm, manage the house, or create Home Assistant changes from natural language.
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {prompts.map((prompt) => (
          <button
            key={prompt}
            className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 text-left text-sm text-slate-300 transition hover:border-white/25 hover:bg-white/[0.08] hover:text-slate-100"
            onClick={() => onPrompt(quickPrompt(prompt))}
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}

function MessageBubble({
  message,
  busy,
  executePreview,
  appendAssistant,
  installDraft,
  confirm,
  cancel,
}: {
  message: Msg;
  busy: boolean;
  executePreview: (msg: Msg) => Promise<void>;
  appendAssistant: (msg: Omit<Msg, "id" | "role">) => void;
  installDraft: (id: number) => Promise<void>;
  confirm: (token: string) => Promise<void>;
  cancel: (token: string) => Promise<void>;
}) {
  const automationDraftId = draftId(message.command);
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[min(42rem,92%)] ${isUser ? "chat-user-bubble" : "chat-assistant-bubble"}`}>
        {message.mode && !isUser && <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-400">{message.mode}</div>}
        {isUser ? (
          <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">{message.text}</div>
        ) : (
          <Markdown text={message.text} />
        )}

        {message.command?.error === "role_not_allowed" && (
          <RoleDeniedCard policy={message.command.data?.policy} />
        )}

        {message.command && (
          <div className="mt-3 space-y-2 rounded-xl border border-white/10 bg-black/20 p-3 text-xs text-slate-300">
            <div className="flex flex-wrap gap-2">
              {message.command.intent && <Badge tone="brand">{message.command.intent}</Badge>}
              {message.command.data?.policy?.decision && <Badge>{message.command.data.policy.decision}</Badge>}
              {message.command.requires_confirmation && <Badge tone="warn">confirmation</Badge>}
              {automationDraftId && <Badge tone="warn">draft {automationDraftId}</Badge>}
            </div>
            <div className="grid gap-1">
              {targetSummary(message.command) && <div><span className="text-slate-500">Target:</span> {targetSummary(message.command)}</div>}
              {serviceSummary(message.command) && <div><span className="text-slate-500">Service:</span> {serviceSummary(message.command)}</div>}
            </div>
            {outcomeLabel(message.command) && (
              <div className={message.command.data?.outcome?.verified === false ? "text-amber-200" : "text-emerald-200"}>
                <span className="text-slate-500">Outcome:</span> {outcomeLabel(message.command)}
              </div>
            )}
            {message.command.data?.security?.pin_required && <div className="text-amber-200">Security PIN required</div>}
            <DeveloperDetails data={{ tool_call: message.command.tool_call, resolved: message.command.resolved, data: message.command.data }} />
          </div>
        )}

        {message.kind === "preview" && (
          <div className="mt-3 flex flex-wrap gap-2">
            <Button className="min-h-9 px-3 py-1.5 text-xs" onClick={() => void executePreview(message)} disabled={busy}>
              {message.command?.requires_confirmation ? "Request confirmation" : PROPOSAL_INTENTS.has(message.command?.intent || "") ? "Create draft" : "Execute"}
            </Button>
            <Button variant="ghost" className="min-h-9 px-3 py-1.5 text-xs" onClick={() => appendAssistant({ text: "Cancelled.", mode: "cancelled" })} disabled={busy}>
              Cancel
            </Button>
          </div>
        )}

        {automationDraftId && message.kind !== "preview" && (
          <div className="mt-3 flex flex-wrap gap-2">
            <Button className="min-h-9 px-3 py-1.5 text-xs" onClick={() => void installDraft(automationDraftId)} disabled={busy}>
              Install in HA
            </Button>
          </div>
        )}

        {message.kind === "confirmation" && message.command?.confirmation_token && (
          <div className="mt-3 rounded-xl border border-amber-400/40 bg-amber-500/10 p-3">
            <div className="font-semibold text-amber-100">Confirm action</div>
            <div className="mt-1 text-xs text-amber-100/80">Review the target and confirm only if it is correct.</div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="warning" className="min-h-9 px-3 py-1.5 text-xs" onClick={() => void confirm(message.command!.confirmation_token!)} disabled={busy}>
                Confirm
              </Button>
              <Button variant="ghost" className="min-h-9 px-3 py-1.5 text-xs" onClick={() => void cancel(message.command!.confirmation_token!)} disabled={busy}>
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function RoleDeniedCard({ policy }: { policy: any }) {
  const role = String(policy?.actual_role || "this login").replace(/_/g, " ");
  const required = String(policy?.required_role || "owner/admin").replace(/_/g, " ");
  return (
    <div className="mt-3 rounded-xl border border-amber-400/35 bg-amber-500/10 p-3 text-xs text-amber-50">
      <div className="font-semibold">Owner-only change blocked</div>
      <div className="mt-1 text-amber-100/80">
        This session is {role}; this action needs {required}. I can still help brainstorm it, but I will not change dashboards,
        discovery, users, permissions, or system setup from a resident/shared login.
      </div>
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
    <section className="min-h-0 flex-1 overflow-y-auto px-3 py-5 sm:px-6">
      <div className="mx-auto max-w-4xl space-y-4">
        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-lg font-semibold text-slate-100">{detail?.messages?.[0]?.message || "Current conversation"}</div>
              <div className="mt-1 truncate text-xs text-slate-500">{conversationId}</div>
            </div>
            <Button onClick={() => void exportMarkdown()} disabled={busy || !detail?.messages?.length}>Download Markdown</Button>
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
          <div className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Transcript</div>
          <div className="max-h-[28rem] space-y-3 overflow-auto pr-1">
            {(detail?.messages || []).map((message: any) => (
              <div key={message.id} className="rounded-xl border border-white/10 bg-black/20 p-3">
                <div className="mb-2 text-xs text-slate-500">{message.created_at}</div>
                <div className="mb-2 text-sm text-slate-200"><span className="text-slate-500">User:</span> {message.message}</div>
                <div className="whitespace-pre-wrap text-sm text-slate-300"><span className="text-slate-500">Assistant:</span> {message.response}</div>
              </div>
            ))}
            {(!detail?.messages || detail.messages.length === 0) && <div className="text-sm text-slate-500">No transcript loaded yet.</div>}
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
          <div className="mb-3 text-lg font-semibold text-slate-100">Notes</div>
          <div className="mb-4 space-y-2">
            {(detail?.notes || []).map((n: any) => (
              <div key={n.id} className="rounded-xl border border-white/10 bg-black/20 p-3">
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
