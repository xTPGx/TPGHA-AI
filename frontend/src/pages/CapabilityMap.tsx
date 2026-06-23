import PageHeader from "../components/PageHeader";

// Mirrors backend/app/discovery/capabilities.py (kept in sync manually).
const DOMAIN_CAPS: Record<string, string[]> = {
  light: ["turn_on", "turn_off", "set_brightness", "set_color", "set_color_temp"],
  switch: ["turn_on", "turn_off"],
  fan: ["turn_on", "turn_off", "set_percentage", "set_preset_mode", "oscillate"],
  climate: ["set_temperature", "set_hvac_mode", "get_current_temperature", "get_target_temperature"],
  lock: ["lock", "unlock_sensitive", "get_status"],
  cover: ["open_sensitive_if_garage", "close", "stop", "get_status"],
  camera: ["view", "snapshot", "stream", "get_status"],
  media_player: ["play", "pause", "stop", "volume", "play_media", "select_source"],
  alarm_control_panel: ["arm_home_sensitive", "arm_away_sensitive", "arm_night_sensitive", "disarm_sensitive", "get_status"],
  siren: ["turn_on_sensitive", "turn_off"],
  vacuum: ["start", "stop", "return_to_base"],
  scene: ["activate"],
  script: ["run"],
  automation: ["enable", "disable", "get_status"],
  person: ["get_status"],
  device_tracker: ["get_status"],
  sensor: ["get_status"],
  binary_sensor: ["get_status"],
  valve: ["open_sensitive", "close"],
};

const RISK: Record<string, string[]> = {
  low: ["lights", "fans", "music", "scenes", "basic switches", "personal device status"],
  medium: ["climate", "appliances", "vacuums", "water heaters", "irrigation close/stop"],
  high: ["cameras", "garage covers", "lock status", "sirens", "alarm arm"],
  critical: ["unlock", "garage open", "alarm disarm", "disable security", "disable camera", "change access code"],
};

const RISK_COLORS: Record<string, string> = {
  low: "text-emerald-300",
  medium: "text-amber-300",
  high: "text-orange-300",
  critical: "text-rose-300",
};

export default function CapabilityMap() {
  return (
    <div>
      <PageHeader title="Capability Map & Risk Rules" subtitle="How domains map to capabilities, and which actions need confirmation" />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="card">
          <div className="mb-3 text-sm font-medium text-slate-300">Capabilities by domain</div>
          <div className="space-y-2 text-sm">
            {Object.entries(DOMAIN_CAPS).map(([domain, caps]) => (
              <div key={domain} className="flex flex-wrap items-center gap-2">
                <span className="w-40 shrink-0 font-mono text-brand">{domain}</span>
                <span className="text-slate-400">
                  {caps.map((c) => (
                    <span
                      key={c}
                      className={`mr-1 inline-block ${
                        c.includes("sensitive") ? "text-rose-300" : ""
                      }`}
                    >
                      {c}
                    </span>
                  ))}
                </span>
              </div>
            ))}
          </div>
          <div className="mt-3 text-xs text-slate-500">
            Capabilities marked in red are sensitive and require confirmation.
          </div>
        </div>

        <div className="card">
          <div className="mb-3 text-sm font-medium text-slate-300">Risk levels</div>
          <div className="space-y-3 text-sm">
            {Object.entries(RISK).map(([level, items]) => (
              <div key={level}>
                <div className={`font-semibold uppercase ${RISK_COLORS[level]}`}>{level}</div>
                <div className="text-slate-400">{items.join(", ")}</div>
              </div>
            ))}
          </div>
          <div className="mt-4 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">
            Critical actions (unlock, garage open, alarm disarm, disable security/camera,
            change access code) never execute from the initial command. They require an
            explicit confirmation token that expires after 60 seconds.
          </div>
        </div>
      </div>
    </div>
  );
}
