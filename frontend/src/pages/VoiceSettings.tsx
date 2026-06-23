import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import PageHeader from "../components/PageHeader";

type Profile = {
  provider: string;
  model: string;
  voice: string;
  instructions?: string;
  output: string;
  response_format: string;
  available: boolean;
  backend?: Record<string, any>;
  assistant: { id: string; name: string; tone?: string };
};

export default function VoiceSettings() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [voices, setVoices] = useState<any[]>([]);
  const [settings, setSettings] = useState<Record<string, any>>({});
  const [selected, setSelected] = useState("atlas");
  const [text, setText] = useState("Voice check complete. I am online and ready.");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const activeProfile = useMemo(
    () => profiles.find((p) => p.assistant.id === selected) || profiles[0],
    [profiles, selected],
  );

  const load = async () => {
    setError(null);
    try {
      const [profileData, voiceData] = await Promise.all([
        api.voiceProfiles(),
        api.voiceVoices(),
      ]);
      setProfiles(profileData.profiles || []);
      setVoices(voiceData.voices || []);
      setSettings(profileData.settings || {});
      if (!selected && profileData.profiles?.[0]?.assistant?.id) {
        setSelected(profileData.profiles[0].assistant.id);
      }
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => {
    void load();
    return () => audioRef.current?.pause();
  }, []);

  const preview = async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await api.voicePreview({ assistant: selected, text });
      setResult(response);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const speak = async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await api.voiceSpeak({ assistant: selected, text });
      setResult(response);
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
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader title="Voice Settings" subtitle="Assistant voices, OpenAI TTS readiness, and playback routing" />

      {error && <div className="mb-4 rounded border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>}

      <div className="mb-5 grid gap-4 md:grid-cols-3">
        <div className="card">
          <div className="text-xs uppercase text-slate-400">OpenAI TTS</div>
          <div className="mt-2 text-2xl font-semibold">{settings.openai_configured ? "ready" : "fallback"}</div>
          <div className="mt-1 text-sm text-slate-400">{settings.openai_tts_model || "gpt-4o-mini-tts"}</div>
        </div>
        <div className="card">
          <div className="text-xs uppercase text-slate-400">Speaker routing</div>
          <div className="mt-2 text-2xl font-semibold">{settings.voice_public_base_url_configured ? "enabled" : "staged"}</div>
          <div className="mt-1 text-sm text-slate-400">Browser playback always remains available</div>
        </div>
        <div className="card">
          <div className="text-xs uppercase text-slate-400">Profiles</div>
          <div className="mt-2 text-2xl font-semibold">{profiles.length}</div>
          <div className="mt-1 text-sm text-slate-400">{voices.length} voice choices listed</div>
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="card">
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <select className="input max-w-[14rem]" value={selected} onChange={(e) => setSelected(e.target.value)}>
              {profiles.map((profile) => (
                <option key={profile.assistant.id} value={profile.assistant.id}>
                  {profile.assistant.name}
                </option>
              ))}
            </select>
            <button className="btn-ghost" onClick={() => void load()} disabled={busy}>
              Refresh
            </button>
          </div>

          {activeProfile && (
            <div className="mb-5 grid gap-3 md:grid-cols-2">
              <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
                <div className="text-xs uppercase text-brand">Profile</div>
                <div className="mt-2 text-lg font-semibold">{activeProfile.assistant.name}</div>
                <div className="mt-1 text-sm text-slate-300">
                  {activeProfile.provider} · {activeProfile.model} · {activeProfile.voice}
                </div>
                <div className="mt-1 text-sm text-slate-400">
                  {activeProfile.available ? "Provider available" : "Using browser fallback until OpenAI is configured"}
                </div>
              </div>
              <div className="rounded border border-slate-700 bg-slate-950/40 p-3">
                <div className="text-xs uppercase text-brand">Delivery</div>
                <div className="mt-2 text-lg font-semibold">{activeProfile.output}</div>
                <div className="mt-1 text-sm text-slate-300">{activeProfile.response_format}</div>
                <div className="mt-1 text-sm text-slate-400">
                  {activeProfile.backend?.speaker_routing_configured ? "HA speaker routes can be called" : "Generated audio plays in browser by default"}
                </div>
              </div>
            </div>
          )}

          <textarea
            className="input min-h-[7rem] w-full"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="mt-4 flex flex-wrap gap-3">
            <button className="btn" onClick={() => void speak()} disabled={busy || !text.trim()}>
              {busy ? "Working..." : "Test Voice"}
            </button>
            <button className="btn-ghost" onClick={() => void preview()} disabled={busy || !text.trim()}>
              Preview Profile
            </button>
          </div>

          {result && (
            <pre className="mt-5 max-h-80 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-200">
              {JSON.stringify({ ...result, audio_base64: result.audio_base64 ? "[audio bytes]" : undefined }, null, 2)}
            </pre>
          )}
        </div>

        <div className="card">
          <div className="mb-3 text-lg font-semibold">Voice Catalog</div>
          <div className="space-y-2">
            {voices.map((voice) => (
              <div key={voice.id} className="rounded border border-slate-700 bg-slate-950/40 p-3">
                <div className="font-semibold">{voice.label}</div>
                <div className="text-xs text-brand">{voice.id}</div>
                <div className="mt-1 text-sm text-slate-400">{voice.style}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
