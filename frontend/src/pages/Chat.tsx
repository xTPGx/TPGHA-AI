import { useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

interface Msg {
  role: "user" | "assistant";
  text: string;
  mode?: string;
}

export default function Chat() {
  const [assistant, setAssistant] = useState("atlas");
  const [user, setUser] = useState("shawn");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    const message = text.trim();
    if (!message) return;
    setText("");
    setBusy(true);
    setError(null);
    setMessages((m) => [...m, { role: "user", text: message }]);
    try {
      const r = await api.chat(assistant, user, message);
      setMessages((m) => [
        ...m,
        { role: "assistant", text: r.response || "Done.", mode: r.mode },
      ]);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader title="Chat" subtitle="Conversational house brain with guarded actions and proposals" />

      <div className="mb-4 flex flex-wrap gap-3">
        <select className="input max-w-[12rem]" value={assistant} onChange={(e) => setAssistant(e.target.value)}>
          <option value="atlas">Atlas</option>
          <option value="chatty">Chatty</option>
        </select>
        <select className="input max-w-[12rem]" value={user} onChange={(e) => setUser(e.target.value)}>
          <option value="shawn">Shawn</option>
          <option value="jordie">Jordie</option>
        </select>
      </div>

      {error && <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      <div className="card mb-4 min-h-[28rem] space-y-3">
        {messages.length === 0 && (
          <div className="text-slate-500">
            Try “set a sleep timer on the office TV in 30 minutes” or “suggest a bedtime routine.”
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
          placeholder="Talk to the house..."
        />
        <button className="btn self-stretch" onClick={send} disabled={busy}>
          {busy ? "Thinking..." : "Send"}
        </button>
      </div>
    </div>
  );
}
