import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import Badge from "../components/Badge";
import Button from "../components/Button";
import DeveloperDetails from "../components/DeveloperDetails";
import PageHeader from "../components/PageHeader";
import ToggleRow from "../components/ToggleRow";
import { homeAssistantSessionHints } from "../haAuth";
import VoiceSources from "./VoiceSources";

const emptyAssistant = {
  id: "",
  name: "",
  owner: "",
  aliases: "",
  wake_words: "",
  listen_enabled: true,
  tone: "confident",
  personality: "",
  voice_provider: "openai",
  voice: "cedar",
  voice_instructions: "",
};

export default function Assistants() {
  const [cfg, setCfg] = useState<any>(null);
  const [voices, setVoices] = useState<any[]>([]);
  const [voiceSettings, setVoiceSettings] = useState<Record<string, any>>({});
  const [voiceText, setVoiceText] = useState("Voice check complete. I am online and ready.");
  const [voiceResult, setVoiceResult] = useState<any>(null);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const [editor, setEditor] = useState<any | null>(null);
  const [session, setSession] = useState<any>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const load = async () => {
    const [config, voiceCatalog, profiles, uiSession] = await Promise.all([
      api.config(),
      api.voiceVoices(),
      api.voiceProfiles(),
      api.uiSession(homeAssistantSessionHints()),
    ]);
    setCfg(config);
    setVoices(voiceCatalog.voices || []);
    setVoiceSettings(profiles.settings || {});
    setSession(uiSession);
  };
  useEffect(() => {
    void load();
    return () => audioRef.current?.pause();
  }, []);

  const sessionRole = session?.role || "guest";
  const activeUserId = session?.detected_user?.id || "";
  const canManageAll = ["admin", "manager"].includes(sessionRole);
  const allAssistants = cfg?.assistants?.assistants ?? [];
  const assistants = canManageAll ? allAssistants : allAssistants.filter((a: any) => a.owner === activeUserId);
  const canCreateOwn = !canManageAll && Boolean(activeUserId) && assistants.length === 0;
  const users = cfg?.assistants?.users ?? [];
  const accounts = cfg?.devices?.music_accounts ?? {};
  const voiceSources = cfg?.devices?.voice_sources ?? [];
  const userById = (id: string) => users.find((u: any) => u.id === id);

  const editAssistant = (assistant?: any) => {
    const voice = typeof assistant?.voice === "object" ? assistant.voice : {};
    const effectiveVoice = assistant ? resolvedVoice(assistant) : { provider: "openai", voice: "cedar" };
    setMessage("");
    setVoiceResult(null);
    setVoiceError("");
    setEditor(assistant ? {
      ...emptyAssistant,
      ...assistant,
      aliases: (assistant.aliases ?? []).join(", "),
      wake_words: (assistant.wake_words ?? defaultWakeWords(assistant.id, assistant.name)).join(", "),
      listen_enabled: assistant.listen_enabled !== false,
      voice_provider: effectiveVoice.provider || voice.provider || "openai",
      voice: effectiveVoice.voice || voice.voice || "cedar",
      voice_instructions: voice.instructions || "",
    } : { ...emptyAssistant, owner: canManageAll ? "" : activeUserId });
  };

  const editorVoiceProfile = () => ({
    provider: editor.voice_provider || "openai",
    model: "gpt-4o-mini-tts",
    voice: editor.voice || "cedar",
    response_format: "mp3",
    output: "browser",
    fallback_provider: "browser",
    instructions: editor.voice_instructions || "",
  });

  const previewVoice = async () => {
    setVoiceBusy(true);
    setVoiceError("");
    try {
      const response = await api.voicePreview({
        assistant: slug(editor.id || editor.name),
        text: voiceText,
        voice_profile: editorVoiceProfile(),
      });
      setVoiceResult(response);
    } catch (e: any) {
      setVoiceError(e.message || String(e));
    } finally {
      setVoiceBusy(false);
    }
  };

  const testVoice = async () => {
    setVoiceBusy(true);
    setVoiceError("");
    try {
      const response = await api.voiceSpeak({
        assistant: slug(editor.id || editor.name),
        text: voiceText,
        voice_profile: editorVoiceProfile(),
      });
      setVoiceResult(response);
      if (response.audio_base64 && response.content_type) {
        audioRef.current?.pause();
        const audio = new Audio(`data:${response.content_type};base64,${response.audio_base64}`);
        audioRef.current = audio;
        await audio.play();
      } else if (response.speak_text && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(response.speak_text));
      }
    } catch (e: any) {
      setVoiceError(e.message || String(e));
    } finally {
      setVoiceBusy(false);
    }
  };

  const saveAssistant = async () => {
    setSaving(true);
    setMessage("");
    try {
      const payload = {
        id: slug(editor.id || editor.name),
        name: editor.name,
        owner: canManageAll ? editor.owner : activeUserId,
        aliases: csv(editor.aliases),
        wake_words: csv(editor.wake_words),
        listen_enabled: Boolean(editor.listen_enabled),
        tone: editor.tone,
        personality: editor.personality,
        voice: {
          provider: editor.voice_provider,
          model: "gpt-4o-mini-tts",
          voice: editor.voice,
          response_format: "mp3",
          output: "browser",
          fallback_provider: "browser",
          instructions: editor.voice_instructions,
        },
      };
      await api.saveAssistant(payload);
      await load();
      setEditor(null);
      setMessage("Assistant saved.");
    } catch (e: any) {
      setMessage(e.message || String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page-stack">
      <PageHeader
        title="Assistants"
        subtitle={canManageAll ? "Create and tune assistant identity, ownership, personality, and voice." : "Tune your own AI profile, voice, wake words, and personality."}
        actions={(canManageAll || canCreateOwn) ? (
          <Button onClick={() => editAssistant()}>{canManageAll ? "Add Assistant" : "Create My Assistant"}</Button>
        ) : undefined}
      />

      {!canManageAll && (
        <div className="rounded-xl border border-sky-400/30 bg-sky-400/10 p-3 text-sm text-sky-100">
          Home Assistant controls your access level. This page only edits your own TPG AI assistant profile.
        </div>
      )}

      {message && <div className="tpg-panel-flat p-3 text-sm">{message}</div>}

      {editor && (
        <div className="card">
          <div className="mb-3 text-lg font-semibold">{editor.id ? "Edit Assistant" : "Add Assistant"}</div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <Field label="ID" value={editor.id} onChange={(v) => setEditor({ ...editor, id: slug(v) })} placeholder="atlas" />
            <Field label="Name" value={editor.name} onChange={(v) => setEditor({ ...editor, name: v })} placeholder="Atlas" />
            <label>
              <div className="mb-1 text-xs uppercase text-slate-500">Owner</div>
              <select className="input" value={canManageAll ? editor.owner : activeUserId} disabled={!canManageAll} onChange={(e) => setEditor({ ...editor, owner: e.target.value })}>
                <option value="">Select owner</option>
                {users.map((u: any) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
            </label>
            <Field label="Tone" value={editor.tone} onChange={(v) => setEditor({ ...editor, tone: v })} placeholder="confident" />
            <Field label="Aliases" value={editor.aliases} onChange={(v) => setEditor({ ...editor, aliases: v })} placeholder="atlas, house" />
            <Field label="Wake Words" value={editor.wake_words} onChange={(v) => setEditor({ ...editor, wake_words: v })} placeholder="atlas, hey atlas" />
            <label>
              <div className="mb-1 text-xs uppercase text-slate-500">Voice</div>
              <select className="input" value={editor.voice} onChange={(e) => setEditor({ ...editor, voice: e.target.value })}>
                {(voices.length ? voices : DEFAULT_VOICES).map((v: any) => <option key={v.id || v} value={v.id || v}>{v.label || v.id || v}</option>)}
              </select>
            </label>
            <ToggleRow
              label="Wake-word listening"
              description="Allow mapped voice sources to route wake phrases to this assistant."
              checked={editor.listen_enabled}
              onChange={(checked) => setEditor({ ...editor, listen_enabled: checked })}
            />
            <label className="md:col-span-2">
              <div className="mb-1 text-xs uppercase text-slate-500">Personality</div>
              <textarea className="input min-h-24" value={editor.personality} onChange={(e) => setEditor({ ...editor, personality: e.target.value })} />
            </label>
            <label className="md:col-span-2">
              <div className="mb-1 text-xs uppercase text-slate-500">Voice instructions</div>
              <textarea className="input min-h-20" value={editor.voice_instructions} onChange={(e) => setEditor({ ...editor, voice_instructions: e.target.value })} />
            </label>
          </div>

          <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
            <div className="tpg-panel-flat p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-lg font-semibold">Voice Test</div>
                  <div className="text-sm text-slate-400">
                    {editor.voice_provider} / {editor.voice} {"->"} browser playback
                  </div>
                </div>
                <Badge tone={voiceSettings.openai_configured ? "good" : "warn"}>
                  OpenAI TTS {voiceSettings.openai_configured ? "ready" : "not configured"}
                </Badge>
              </div>
              <textarea className="input min-h-24" value={voiceText} onChange={(e) => setVoiceText(e.target.value)} />
              <div className="mt-3 flex flex-wrap gap-2">
                <Button onClick={() => void testVoice()} disabled={voiceBusy || !voiceText.trim()}>
                  {voiceBusy ? "Working..." : "Test Voice"}
                </Button>
                <Button variant="ghost" onClick={() => void previewVoice()} disabled={voiceBusy || !voiceText.trim()}>
                  Preview Voice
                </Button>
              </div>
              {voiceError && <div className="mt-3 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">{voiceError}</div>}
              {voiceResult && (
                <div className="mt-3 space-y-2 text-sm">
                  <Row label="TTS provider" value={voiceResult.provider === "browser" ? `browser fallback${voiceResult.fallback_reason ? `: ${voiceResult.fallback_reason}` : ""}` : voiceResult.provider} />
                  <Row label="Voice profile" value={`${voiceResult.profile?.provider || editor.voice_provider} / ${voiceResult.profile?.voice || editor.voice}`} />
                  <Row label="Playback" value={voiceResult.profile?.route?.output || voiceResult.profile?.output || "browser"} />
                  <DeveloperDetails
                    title="Voice debug"
                    data={{ ...voiceResult, audio_base64: voiceResult.audio_base64 ? "[audio bytes]" : undefined }}
                  />
                </div>
              )}
            </div>

            <div className="tpg-panel-flat p-4">
              <div className="mb-3 text-lg font-semibold">Voice Catalog</div>
              <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
                {(voices.length ? voices : DEFAULT_VOICES.map((id) => ({ id, label: id }))).map((voice: any) => (
                  <button
                    key={voice.id}
                    className={`tpg-panel-flat block w-full px-3 py-2 text-left ${editor.voice === voice.id ? "border-brand bg-brand-dark/20" : ""}`}
                    onClick={() => setEditor({ ...editor, voice: voice.id })}
                  >
                    <div className="font-semibold">{voice.label || voice.id}</div>
                    <div className="font-mono text-xs text-brand">{voice.id}</div>
                    {voice.style && <div className="mt-1 text-xs text-slate-400">{voice.style}</div>}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-4 flex gap-2">
            <Button onClick={saveAssistant} disabled={saving || !editor.name || !(canManageAll ? editor.owner : activeUserId)}>Save Assistant</Button>
            <Button variant="ghost" onClick={() => setEditor(null)}>Cancel</Button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {assistants.map((a: any) => {
          const owner = userById(a.owner);
          const acct = owner?.music_account ? accounts[owner.music_account] : null;
          const voice = resolvedVoice(a);
          const sources = voiceSources.filter((source: any) => source.assistant === a.id || (!source.assistant && source.user === a.owner));
          const wakeWords = a.wake_words?.length ? a.wake_words : defaultWakeWords(a.id, a.name);
          return (
            <div key={a.id} className="card">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-xl font-bold text-brand">{a.name}</div>
                  <span className="badge bg-slate-700 text-slate-300">{a.tone}</span>
                </div>
                <Button variant="ghost" onClick={() => editAssistant(a)}>Edit</Button>
              </div>
              <p className="mt-2 text-sm text-slate-300">{a.personality}</p>
              <dl className="mt-4 space-y-1 text-sm">
                <Row label="Owner" value={owner ? owner.name : a.owner} />
                <Row label="Voice" value={`${voice.provider} / ${voice.voice}`} />
                <Row label="Wake words" value={wakeWords.join(", ")} />
                <Row label="Wake deployment" value={`${sources.length} linked source${sources.length === 1 ? "" : "s"}`} />
                <Row label="Music account" value={acct ? acct.name : owner?.music_account} />
                <Row label="Aliases" value={(a.aliases ?? []).join(", ")} />
              </dl>
              {sources.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {sources.map((source: any) => (
                    <Badge key={source.id} tone="brand">{source.name} · {source.room}</Badge>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <section className="mt-8">
        {canManageAll && <VoiceSources embedded />}
      </section>
    </div>
  );
}

function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return (
    <label>
      <div className="mb-1 text-xs uppercase text-slate-500">{label}</div>
      <input className="input" value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
    </label>
  );
}

function Row({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-200">{value}</dd>
    </div>
  );
}

function csv(value: string) {
  return String(value || "").split(",").map((v) => v.trim()).filter(Boolean);
}

function slug(value: string) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

const DEFAULT_VOICES = ["cedar", "coral", "nova", "onyx", "marin", "sage", "verse", "ballad", "ash", "echo", "fable", "shimmer"];

function defaultWakeWords(id: string, name: string) {
  const base = String(id || name || "").trim().toLowerCase();
  return base ? [base] : [];
}

function resolvedVoice(assistant: any) {
  const defaultVoice = assistant?.id === "chatty" ? "coral" : "cedar";
  if (typeof assistant?.voice === "object") {
    const provider = String(assistant.voice.provider || "").toLowerCase();
    const voice = String(assistant.voice.voice || "").toLowerCase();
    if (provider === "browser" && ["", "neutral", "default", "alloy"].includes(voice) && ["atlas", "chatty"].includes(assistant?.id)) {
      return { provider: "openai", voice: defaultVoice };
    }
    return {
      provider: assistant.voice.provider || "openai",
      voice: ["", "neutral", "default"].includes(voice) ? defaultVoice : assistant.voice.voice,
    };
  }
  const raw = String(assistant?.voice || "").toLowerCase();
  if (assistant?.id === "atlas" && (!raw || raw === "neutral" || raw === "default")) {
    return { provider: "openai", voice: "cedar" };
  }
  if (assistant?.id === "chatty" && (!raw || raw === "bright" || raw === "default")) {
    return { provider: "openai", voice: "coral" };
  }
  if (raw === "bright") return { provider: "openai", voice: "coral" };
  if (raw === "neutral") return { provider: "browser", voice: "alloy" };
  return { provider: "openai", voice: raw || "cedar" };
}
