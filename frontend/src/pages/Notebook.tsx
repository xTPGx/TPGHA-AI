import { useEffect, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

export default function Notebook() {
  const [sessions, setSessions] = useState<any[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [detail, setDetail] = useState<any>(null);
  const [session, setSession] = useState<any>(null);
  const [assistantFilter, setAssistantFilter] = useState("");
  const [userFilter, setUserFilter] = useState("");
  const [note, setNote] = useState({ title: "Session note", body: "" });
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<any[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canBrowseProfiles = ["admin", "manager"].includes(session?.role);

  const loadSessions = async () => {
    try {
      const response = await api.conversations(80, {
        assistant: assistantFilter || undefined,
        user: userFilter || undefined,
      });
      const list = response.conversations || [];
      setSessions(list);
      if (list[0]?.conversation_id && !list.some((item: any) => item.conversation_id === selected)) {
        setSelected(list[0].conversation_id);
      } else if (!list.length) {
        setSelected("");
        setDetail(null);
      }
      setError(null);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  };

  const loadDetail = async (conversationId: string) => {
    if (!conversationId) return;
    try {
      const response = await api.conversation(conversationId);
      setDetail(response);
      setError(null);
    } catch (e: any) {
      setError(e.message || String(e));
    }
  };

  useEffect(() => {
    api.uiSession().then((result) => {
      setSession(result);
      const defaultUser = result.detected_user?.id || "";
      const defaultAssistant = result.default_assistant?.id || "";
      setUserFilter(defaultUser);
      setAssistantFilter(defaultAssistant);
    }).catch(() => {
      void loadSessions();
    });
  }, []);

  useEffect(() => {
    void loadDetail(selected);
  }, [selected]);

  useEffect(() => {
    void loadSessions();
  }, [assistantFilter, userFilter]);

  const addNote = async () => {
    if (!selected || !note.body.trim()) return;
    setBusy("note");
    setError(null);
    try {
      await api.addConversationNote(selected, {
        title: note.title,
        body: note.body,
        assistant: detail?.messages?.at(-1)?.assistant || "",
        user: detail?.messages?.at(-1)?.user || "",
        source: "web_ui",
      });
      setNote({ title: "Session note", body: "" });
      await loadDetail(selected);
      await loadSessions();
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(null);
    }
  };

  const exportMarkdown = async () => {
    if (!selected) return;
    setBusy("export");
    setError(null);
    try {
      const response = await api.exportConversation(selected);
      const blob = new Blob([response.markdown || ""], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = response.filename || `tpg-homeai-${selected}.md`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(null);
    }
  };

  const runSearch = async () => {
    if (!query.trim()) return;
    setBusy("search");
    setError(null);
    try {
      const response = await api.researchSearch(query, 5);
      setResults(response.results || []);
      if (response.error && !(response.results || []).length) setError(response.error);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <PageHeader
        title="Notebook"
        subtitle="Profile-aware conversation history, research, notes, and exportable transcripts"
        actions={<button className="btn-ghost" onClick={() => void loadSessions()}>Refresh</button>}
      />

      {error && <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      {canBrowseProfiles ? (
        <div className="mb-4 flex flex-wrap gap-3">
          <select className="input max-w-[14rem]" value={assistantFilter} onChange={(e) => setAssistantFilter(e.target.value)}>
            <option value="">All profiles</option>
            {(session?.assistants || []).map((a: any) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
          <select className="input max-w-[14rem]" value={userFilter} onChange={(e) => setUserFilter(e.target.value)}>
            <option value="">All users</option>
            {(session?.users || []).map((u: any) => (
              <option key={u.id} value={u.id}>{u.name}</option>
            ))}
          </select>
        </div>
      ) : (
        <div className="mb-4 rounded-lg border border-slate-800 bg-slate-950/30 px-3 py-2 text-sm text-slate-400">
          Showing {session?.default_assistant?.name || "your assistant"} history for {session?.detected_user?.name || "your profile"}.
        </div>
      )}

      <div className="mb-4 grid grid-cols-1 gap-4 xl:grid-cols-[22rem_1fr]">
        <div className="card">
          <div className="mb-3 text-sm font-semibold uppercase text-slate-400">Sessions</div>
          <div className="space-y-2">
            {sessions.map((session) => (
              <button
                key={session.conversation_id}
                className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${
                  selected === session.conversation_id
                    ? "border-brand bg-brand-dark/20 text-slate-100"
                    : "border-slate-800 bg-slate-950/30 text-slate-300 hover:border-slate-600"
                }`}
                onClick={() => setSelected(session.conversation_id)}
              >
                <div className="line-clamp-2 font-medium">{session.title}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {session.message_count} messages · {session.note_count} notes
                </div>
              </button>
            ))}
            {sessions.length === 0 && <div className="text-sm text-slate-500">No saved conversations yet.</div>}
          </div>
        </div>

        <div className="space-y-4">
          <div className="card">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-lg font-semibold text-slate-100">{detail?.messages?.[0]?.message || "Conversation"}</div>
                <div className="text-xs text-slate-500">{selected || "Select a session"}</div>
              </div>
              <button className="btn" onClick={() => void exportMarkdown()} disabled={!selected || busy === "export"}>
                Download Markdown
              </button>
            </div>

            <div className="max-h-[30rem] space-y-3 overflow-auto pr-1">
              {(detail?.messages || []).map((message: any) => (
                <div key={message.id} className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
                  <div className="mb-2 text-xs text-slate-500">{message.created_at}</div>
                  <div className="mb-2 text-sm text-slate-200"><span className="text-slate-500">User:</span> {message.message}</div>
                  <div className="whitespace-pre-wrap text-sm text-slate-300"><span className="text-slate-500">Assistant:</span> {message.response}</div>
                  {message.intent && message.intent !== "conversation" && (
                    <div className="mt-2 text-xs text-brand">intent: {message.intent}</div>
                  )}
                </div>
              ))}
              {(!detail?.messages || detail.messages.length === 0) && <div className="text-sm text-slate-500">No transcript loaded.</div>}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="card">
              <div className="mb-3 text-lg font-semibold text-slate-100">Notes</div>
              <div className="mb-3 space-y-2">
                {(detail?.notes || []).map((n: any) => (
                  <div key={n.id} className="rounded border border-slate-800 bg-slate-950/40 p-3">
                    <div className="text-sm font-semibold text-slate-200">{n.title}</div>
                    <div className="mt-1 whitespace-pre-wrap text-sm text-slate-400">{n.body}</div>
                  </div>
                ))}
                {(!detail?.notes || detail.notes.length === 0) && <div className="text-sm text-slate-500">No notes attached.</div>}
              </div>
              <input className="input mb-2" value={note.title} onChange={(e) => setNote({ ...note, title: e.target.value })} placeholder="Note title" />
              <textarea className="input min-h-[7rem]" value={note.body} onChange={(e) => setNote({ ...note, body: e.target.value })} placeholder="Capture decisions, ideas, next steps, or anything you want exported with this session." />
              <button className="btn mt-3" onClick={() => void addNote()} disabled={!selected || !note.body.trim() || busy === "note"}>
                Add Note
              </button>
            </div>

            <div className="card">
              <div className="mb-3 text-lg font-semibold text-slate-100">Research</div>
              <div className="flex gap-2">
                <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => {
                  if (e.key === "Enter") void runSearch();
                }} placeholder="Search the web..." />
                <button className="btn" onClick={() => void runSearch()} disabled={!query.trim() || busy === "search"}>
                  Search
                </button>
              </div>
              <div className="mt-3 space-y-2">
                {results.map((result) => (
                  <a key={result.url} className="block rounded border border-slate-800 bg-slate-950/40 p-3 hover:border-brand-dark" href={result.url} target="_blank" rel="noreferrer">
                    <div className="text-sm font-semibold text-brand">{result.title}</div>
                    <div className="mt-1 text-xs text-slate-400">{result.snippet}</div>
                    <div className="mt-1 truncate text-xs text-slate-600">{result.url}</div>
                  </a>
                ))}
                {results.length === 0 && <div className="text-sm text-slate-500">Search results will appear here.</div>}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
