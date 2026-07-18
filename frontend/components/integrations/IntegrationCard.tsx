"use client";

import { Link2, Loader2, RefreshCw, Unplug } from "lucide-react";

import { IntegrationStatusBadge, type IntegrationConnectionState } from "./IntegrationStatusBadge";

export interface IntegrationCardData {
  key: string;
  providerKey: string;
  title: string;
  description: string;
  capabilities: string[];
  requirements?: string[];
  logo: string;
  logoUrl: string;
  logoTone: string;
  connected: boolean;
  connectedAt: string | null;
  connectedLabel?: string;
  connectedValue?: string;
  connectedDetails?: Array<{ label: string; value: string }>;
  connectionState?: IntegrationConnectionState;
  errorMessage?: string;
  statusDetail?: string;
  runtimeState?: "available" | "connection_only" | string;
  connectLabel: string;
  action: "oauth" | "manual" | "secret" | "disabled";
}

type IntegrationCardProps = {
  card: IntegrationCardData;
  token?: string;
  target?: string;
  tokenLabel?: string;
  tokenPlaceholder?: string;
  targetPlaceholder?: string;
  statusText?: string;
  configuring?: boolean;
  onTokenChange?: (value: string) => void;
  onTargetChange?: (value: string) => void;
  onConnect?: () => void;
  onReconnect?: () => void;
  onDisconnect?: () => void;
  onCancelConfigure?: () => void;
};

export function IntegrationCard({
  card,
  token,
  target,
  tokenLabel = "Token",
  tokenPlaceholder = "Paste token",
  targetPlaceholder = "Channel or group",
  statusText,
  configuring = false,
  onTokenChange,
  onTargetChange,
  onConnect,
  onReconnect,
  onDisconnect,
  onCancelConfigure,
}: IntegrationCardProps) {
  const state = card.connectionState || (card.connected ? "connected" : "not_connected");
  const connecting = state === "connecting";
  const unavailable = state === "unavailable" || card.action === "disabled";
  const reconnect = state === "expired" || state === "reconnect_required" || state === "error";
  const manualForm = configuring && Boolean(onTokenChange);
  const canSubmit = !manualForm || Boolean(token && token.trim().length >= (onTargetChange ? 9 : 6) && (!onTargetChange || target?.trim()));

  return (
    <article className={`integration-card${card.connected ? " is-connected" : ""}`}>
      <div className="integration-card-head">
        <span className={`integration-logo app-logo-${card.logoTone}`}>
          <img
            src={card.logoUrl}
            alt=""
            onError={(event) => {
              event.currentTarget.hidden = true;
              const fallback = event.currentTarget.nextElementSibling as HTMLElement | null;
              if (fallback) fallback.hidden = false;
            }}
          />
          <span hidden>{card.logo}</span>
        </span>
        <div className="integration-card-title">
          <h3>{card.title}</h3>
          <IntegrationStatusBadge state={state} connected={card.connected} />
        </div>
      </div>

      <div className="integration-card-body">
        <p>{card.description}</p>
        {card.runtimeState === "connection_only" ? (
          <small className="integration-runtime-note">Account connection is available; agent actions are not enabled yet.</small>
        ) : null}
        {card.requirements?.length && !card.connected ? (
          <div className="integration-requirements">
            <strong>Requirements</strong>
            <span>{card.requirements.join(" · ")}</span>
          </div>
        ) : null}
        {card.connectedValue && (card.connected || reconnect) ? (
          <div className="integration-account">
            <span>{card.connectedLabel || "Connected as"}</span>
            <strong>{card.connectedValue}</strong>
          </div>
        ) : null}
        {manualForm ? (
          <div className="integration-fields">
            <label>
              <span>{tokenLabel}</span>
              <input
                type="password"
                value={token || ""}
                placeholder={tokenPlaceholder}
                autoComplete="new-password"
                onChange={(event) => onTokenChange?.(event.target.value)}
              />
            </label>
            {onTargetChange ? (
              <label>
                <span>Channel / group</span>
                <input
                  type="text"
                  value={target || ""}
                  placeholder={targetPlaceholder}
                  autoComplete="off"
                  onChange={(event) => onTargetChange(event.target.value)}
                />
              </label>
            ) : null}
          </div>
        ) : null}
        {card.errorMessage || statusText || card.statusDetail ? (
          <small className={card.errorMessage ? "integration-error" : "integration-detail"}>
            {card.errorMessage || statusText || card.statusDetail}
          </small>
        ) : null}
      </div>

      <div className="integration-card-actions">
        {manualForm ? (
          <>
            <button className="integration-action primary" type="button" disabled={!canSubmit || connecting} onClick={onConnect}>
              {connecting ? <Loader2 className="spin" size={15} /> : <Link2 size={15} />}
              {connecting ? "Connecting..." : card.connectLabel}
            </button>
            <button className="integration-action" type="button" onClick={onCancelConfigure}>Cancel</button>
          </>
        ) : card.connected && !reconnect ? (
          <>
            <button className="integration-action primary" type="button" onClick={onReconnect}>
              <Link2 size={15} /> Manage Connection
            </button>
            <button className="integration-action danger" type="button" aria-label={`Disconnect ${card.title}`} onClick={onDisconnect}>
              <Unplug size={15} />
            </button>
          </>
        ) : (
          <button className="integration-action primary" type="button" disabled={connecting || unavailable} onClick={onConnect}>
            {connecting ? <Loader2 className="spin" size={15} /> : reconnect ? <RefreshCw size={15} /> : <Link2 size={15} />}
            {unavailable ? "Unavailable" : connecting ? "Connecting..." : reconnect ? "Reconnect" : card.connectLabel}
          </button>
        )}
      </div>
    </article>
  );
}
