import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

interface Msg {
  role: "user" | "assistant";
  text: string;
  mode?: string;
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

function getSpeechRecognition(): SpeechRecognitionCtor | null {
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export default function Chat() {
  const conversationId = useMemo(
    () => (crypto?.randomUUID ? crypto.randomUUID() : `chat-${Date.now()}`),
    [],
  );
  const [assistant, setAssistant] = useState("atlas");
  const [user, setUser] = useState("shawn");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const [speakResponses, setSpeakResponses] = useState(true);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const recognitionRef = useRef<InstanceType<SpeechRecognitionCtor> | null>(null);
  const speechSupported = Boolean(getSpeechRecognition());

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
      window.speechSynthesis?.cancel();
    };
  }, []);

  const speak = (message: string) => {
    if (!speakResponses || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(message);
    utterance.rate = 1;
    utterance.pitch = assistant === "chatty" ? 1.08 : 0.95;
    window.speechSynthesis.speak(utterance);
  };

  const send = async (override?: string) => {
    const message = (override ?? text).trim();
    if (!message) return;
    setText("");
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { role: "user", text: message }]);
    try {
      const r = await api.chat(assistant, user, message, conversationId);
      const response = r.response || "Done.";
      setMessages((m) => [
        ...m,
        { role: "assistant", text: response, mode: r.mode },
      ]);
      speak(response);
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
      <PageHeader title="Chat" subtitle="Conversational house brain with guarded actions and proposals" />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select className="input max-w-[12rem]" value={assistant} onChange={(e) => setAssistant(e.target.value)}>
          <option value="atlas">Atlas</option>
          <option value="chatty">Chatty</option>
        </select>
        <select className="input max-w-[12rem]" value={user} onChange={(e) => setUser(e.target.value)}>
          <option value="shawn">Shawn</option>
          <option value="jordie">Jordie</option>
        </select>
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
            Try "set a sleep timer on the office TV in 30 minutes" or "suggest a bedtime routine."
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
            <div className={`inline-block max-w-[80%] rounded-lg border px-3 py-2 text-sm ${
              m.role === "user"
                ? "border-brand-dark bg-brand-dark/20 text-slate-100"
                : "border-slate-700 bg-slate-950/60 text-slate-200"
            }`}>
              {m.mode && <div className="mb-1 text-xs uppercase text-brand">{m.mode}</div>}
              <div className="whitespace-pre-wrap">{m.text}</div>
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
              send();
            }
          }}
          placeholder={listening ? "Listening..." : "Talk to the house..."}
        />
        <button className="btn self-stretch" onClick={() => void send()} disabled={busy}>
          {busy ? "Thinking..." : "Send"}
        </button>
      </div>
    </div>
  );
}
