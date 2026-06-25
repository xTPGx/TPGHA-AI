import { useEffect, useState } from "react";
import { api } from "../api";
import Button from "../components/Button";
import PageHeader from "../components/PageHeader";
import { debugClientHints, homeAssistantSessionHints } from "../haAuth";
import { ingressBasePath } from "../ingress";

function Json({ value }: { value: any }) {
  return (
    <pre className="overflow-auto rounded-lg border border-slate-700/60 bg-slate-950/60 p-3 text-xs text-slate-300">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card">
      <div className="mb-2 text-sm font-medium text-slate-300">{title}</div>
      {children}
    </div>
  );
}

export default function IdentityDebug() {
  const [clientHints, setClientHints] = useState<any>(null);
  const [sessionBody, setSessionBody] = useState<any>(null);
  const [session, setSession] = useState<any>(null);
  const [serverDebug, setServerDebug] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setError(null);
    try {
      const hints = homeAssistantSessionHints();
      setClientHints(debugClientHints());
      setSessionBody({
        ha_access_token: hints.accessToken ? `present (${hints.accessToken.length} chars)` : "",
        ha_client_user: hints.clientUser || {},
      });
      const [s, d] = await Promise.all([
        api.uiSession(hints),
        api.uiSessionDebug(),
      ]);
      setSession(s);
      setServerDebug(d);
    } catch (e: any) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const selected = session?.detected_user;

  return (
    <div className="page-stack">
      <PageHeader
        title="Identity Debug"
        subtitle="Exactly how TPG HomeAI resolves the active Home Assistant user"
        actions={<Button onClick={load}>Re-run</Button>}
      />
      {error && (
        <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-rose-200">{error}</div>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="card">
          <div className="text-xs text-slate-500">App version</div>
          <div className="text-lg font-semibold text-slate-100">{serverDebug?.version || "?"}</div>
        </div>
        <div className="card">
          <div className="text-xs text-slate-500">Identity source</div>
          <div className="text-lg font-semibold text-slate-100">{session?.identity_source || "?"}</div>
        </div>
        <div className="card">
          <div className="text-xs text-slate-500">Trusted</div>
          <div className={`text-lg font-semibold ${session?.identity_trusted ? "text-emerald-300" : "text-amber-300"}`}>
            {session?.identity_trusted ? "yes" : "no"}
          </div>
        </div>
        <div className="card">
          <div className="text-xs text-slate-500">Ingress request</div>
          <div className={`text-lg font-semibold ${serverDebug?.is_ingress_request ? "text-emerald-300" : "text-rose-300"}`}>
            {serverDebug?.is_ingress_request ? "yes" : "no"}
          </div>
        </div>
      </div>

      <Section title="Selected TPG user">
        <Json value={{ id: selected?.id, name: selected?.name, role: session?.role, default_assistant: session?.default_assistant?.name }} />
      </Section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Section title="Frontend path / ingress base">
          <Json value={{ ingressBasePath: ingressBasePath(), ...clientHints }} />
        </Section>
        <Section title="POST /ui/session body sent">
          <Json value={sessionBody} />
        </Section>
        <Section title="Backend ingress headers (X-Remote-User-*)">
          <Json value={serverDebug?.headers} />
        </Section>
        <Section title="Backend candidates + matches">
          <Json value={{ candidates: serverDebug?.candidates, matches: serverDebug?.matches, admin_from_headers: serverDebug?.admin_from_headers }} />
        </Section>
        <Section title="/ui/session response">
          <Json value={{
            detected_user: session?.detected_user,
            role: session?.role,
            identity_source: session?.identity_source,
            identity_trusted: session?.identity_trusted,
            ha_user_candidates: session?.ha_user_candidates,
            ha_admin: session?.ha_admin,
            unknown_ha_user: session?.unknown_ha_user,
            identity_warning: session?.identity_warning,
          }} />
        </Section>
        <Section title="Configured TPG users">
          <Json value={serverDebug?.tpg_users} />
        </Section>
      </div>
    </div>
  );
}
