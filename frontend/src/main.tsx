import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";
import { ingressBasePath } from "./ingress";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter basename={ingressBasePath() || undefined}>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
