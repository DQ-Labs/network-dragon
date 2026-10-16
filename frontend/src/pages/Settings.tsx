import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { write } from "../api/client";
import {
  Heading,
  useData,
  Panel,
  Empty,
  ErrorBox,
  Badge,
  time,
  Row,
} from "../components/ui";
export function Settings() {
  const { data, error } = useData("/settings"),
    networks = useData("/networks"),
    query = useQueryClient(),
    [err, setErr] = useState<Error | null>(null);
  async function update(path: string, method: string, body: Row) {
    try {
      await write(path, method, body);
      setErr(null);
      query.invalidateQueries();
    } catch (e) {
      setErr(e as Error);
    }
  }
  if (!data)
    return error ? (
      <ErrorBox error={error} />
    ) : (
      <Empty>Loading configuration…</Empty>
    );
  return (
    <>
      <Heading
        eyebrow="INSTALLATION"
        title="Deliberate defaults. Clear boundaries."
        description="One administrator, one scanner, and explicit permission to reach your network."
      />
      <ErrorBox error={err} />
      <Panel
        title="Monitored networks"
        subtitle="Every new scope begins in baseline review."
      >
        <div className="network-list">
          {((networks.data as unknown as Row[]) || []).map((n) => (
            <div className="network-card" key={n.id}>
              <div>
                <h3>
                  {n.name} <span className="pill">{n.mode}</span>
                </h3>
                <code>{n.cidr}</code>
                <p>{n.health_reason}</p>
                <small>Last discovery: {time(n.last_discovery)}</small>
              </div>
              <div className="network-actions">
                <Badge state={n.baseline ? "baseline_review" : "reviewed"} />
                {n.baseline && (
                  <button
                    disabled={n.health !== "healthy"}
                    onClick={() =>
                      update(`/networks/${n.id}`, "PATCH", {
                        activate_notifications: true,
                      })
                    }
                  >
                    Finish baseline review
                  </button>
                )}
                <button
                  onClick={() =>
                    update(`/networks/${n.id}`, "PATCH", {
                      enabled: !n.enabled,
                    })
                  }
                >
                  {n.enabled ? "Stop monitoring" : "Enable monitoring"}
                </button>
                {n.health === "suspect" && (
                  <button
                    onClick={() =>
                      update(`/networks/${n.id}`, "PATCH", {
                        acknowledge_guard: true,
                      })
                    }
                  >
                    Acknowledge warning
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
        <details className="settings-details">
          <summary>Add an explicitly configured network</summary>
          <form
            className="form inline-form"
            onSubmit={(e) => {
              e.preventDefault();
              update(
                "/networks",
                "POST",
                Object.fromEntries(new FormData(e.currentTarget)),
              );
            }}
          >
            <label>
              Name
              <input name="name" required />
            </label>
            <label>
              IPv4 CIDR
              <input
                name="cidr"
                required
                placeholder="Numeric CIDR, up to 256 addresses"
              />
            </label>
            <label>
              Interface
              <input name="interface" placeholder="Required for live mode" />
            </label>
            <label>
              Mode
              <select name="mode">
                <option value="fixture">Fixture</option>
                <option value="live">Live (allowlist required)</option>
              </select>
            </label>
            <button className="primary">Add network</button>
          </form>
        </details>
      </Panel>
      <div className="two-column">
        <Panel
          title="Observation & retention"
          subtitle="Edit installation defaults in the server TOML; restart web and worker."
        >
          <div className="policy-list">
            {[
              ["Discovery", `${data.discovery_seconds}s`],
              ["Port scan cadence", `${data.ports_seconds}s`],
              [
                "Offline threshold",
                `${data.offline_misses} misses + ${data.offline_seconds}s`,
              ],
              ["Detailed evidence", `${data.retention_observations_days} days`],
              ["Change history", `${data.retention_events_days} days`],
              ["Delivery attempts", `${data.retention_delivery_days} days`],
              [
                "Database",
                `${(data.database_bytes / 1024 / 1024).toFixed(2)} MiB`,
              ],
              [
                "Last backup",
                data.last_backup
                  ? time(data.last_backup.at)
                  : "No backup recorded",
              ],
            ].map(([key, value]) => (
              <div key={key}>
                {key}
                <span>{value}</span>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Access & boundaries">
          <div className="policy-list">
            <div>
              Live scanning
              <span>
                {data.live_scanning ? "Explicitly enabled" : "Disabled"}
              </span>
            </div>
            <div>
              Notifications
              <span>{data.notifications ? "Enabled" : "Disabled"}</span>
            </div>
            <div>
              Credentials
              <span>
                {data.credentials_configured ? "Configured" : "Not configured"}
              </span>
            </div>
            <div>
              Allowed CIDRs
              <span>{data.allowed_cidrs.join(", ") || "None"}</span>
            </div>
            <div>
              Allowed interfaces
              <span>{data.allowed_interfaces.join(", ") || "None"}</span>
            </div>
            <div>
              Port notifications<span>Never</span>
            </div>
          </div>
          <details className="settings-details">
            <summary>Change administrator password</summary>
            <form
              className="form"
              onSubmit={async (e) => {
                e.preventDefault();
                try {
                  await write(
                    "/session/password",
                    "PUT",
                    Object.fromEntries(new FormData(e.currentTarget)),
                  );
                  location.href = "/";
                } catch (e) {
                  setErr(e as Error);
                }
              }}
            >
              <label>
                Current password
                <input
                  name="current_password"
                  type="password"
                  autoComplete="current-password"
                  required
                />
              </label>
              <label>
                New password
                <input
                  name="new_password"
                  type="password"
                  minLength={12}
                  maxLength={256}
                  autoComplete="new-password"
                  required
                />
              </label>
              <button>Change password & sign out</button>
            </form>
          </details>
        </Panel>
      </div>
    </>
  );
}
