const DEFAULT_INGRESS_URL = "/api/hassio_ingress/3e5a55d6_tpg_homeai";

class TPGHomeAIPanel extends HTMLElement {
  set hass(value) {
    this._hass = value;
    this._syncUser();
  }

  set panel(value) {
    this._panel = value;
    this._render();
  }

  set narrow(value) {
    this._narrow = value;
  }

  set route(value) {
    this._route = value;
  }

  connectedCallback() {
    this._render();
    this._syncUser();
  }

  _render() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }
    const ingressUrl = this._panel?.config?.url || DEFAULT_INGRESS_URL;
    const user = this._safeUser();
    const userHash = user ? `#tpg_ha_user=${encodeURIComponent(btoa(unescape(encodeURIComponent(JSON.stringify(user)))))}` : "";
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
          width: 100%;
          background: #070d18;
        }
        iframe {
          border: 0;
          display: block;
          height: 100vh;
          width: 100%;
          background: #070d18;
        }
      </style>
      <iframe
        id="tpg-frame"
        title="TPG HomeAI"
        src="${ingressUrl}${userHash}"
        allow="microphone; autoplay; clipboard-read; clipboard-write"
      ></iframe>
    `;
    this.shadowRoot.getElementById("tpg-frame")?.addEventListener("load", () => this._syncUser());
  }

  _syncUser() {
    const frame = this.shadowRoot?.getElementById("tpg-frame");
    const user = this._safeUser();
    if (!frame || !user) return;
    frame.contentWindow?.postMessage({
      type: "tpg-homeai-ha-user",
      user,
    }, window.location.origin);
  }

  _safeUser() {
    const user = this._hass?.user;
    if (!user) return null;
    const out = {};
    for (const key of ["id", "name", "username", "display_name", "is_admin", "is_owner"]) {
      if (user[key] !== undefined && user[key] !== null) out[key] = user[key];
    }
    return Object.keys(out).length ? out : null;
  }
}

if (!customElements.get("tpg-homeai-panel")) {
  customElements.define("tpg-homeai-panel", TPGHomeAIPanel);
}
