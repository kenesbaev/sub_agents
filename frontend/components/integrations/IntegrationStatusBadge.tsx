"use client";

import { AlertCircle, CheckCircle2, Clock3, MinusCircle } from "lucide-react";

export type IntegrationConnectionState =
  | "not_connected"
  | "connecting"
  | "connected"
  | "expired"
  | "reconnect_required"
  | "error"
  | "unavailable"
  | string;

export function integrationStatus(state: IntegrationConnectionState, connected = false) {
  const value = state || (connected ? "connected" : "not_connected");
  if (value === "connected") return { label: "Connected", tone: "connected", Icon: CheckCircle2 };
  if (value === "connecting") return { label: "Connecting", tone: "connecting", Icon: Clock3 };
  if (value === "expired" || value === "reconnect_required") {
    return { label: "Reconnect required", tone: "warning", Icon: AlertCircle };
  }
  if (value === "error") return { label: "Connection error", tone: "warning", Icon: AlertCircle };
  if (value === "unavailable") return { label: "Unavailable", tone: "unavailable", Icon: MinusCircle };
  return { label: "Not connected", tone: "neutral", Icon: MinusCircle };
}

export function IntegrationStatusBadge({ state, connected = false }: { state: IntegrationConnectionState; connected?: boolean }) {
  const status = integrationStatus(state, connected);
  return (
    <span className={`integration-status ${status.tone}`}>
      <status.Icon size={12} strokeWidth={2.5} aria-hidden="true" />
      {status.label}
    </span>
  );
}
