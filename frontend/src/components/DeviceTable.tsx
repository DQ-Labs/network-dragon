import type { ReactNode } from "react";
import {
  Server,
  Eye,
  EyeOff,
  BellOff,
  Archive,
  Check,
  Clock3,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
} from "lucide-react";
import {
  type Row,
  Empty,
  ErrorBox,
  Badge,
  Status,
  When,
  label,
  time,
  isMuted,
  needsReview,
  useDeviceActions,
} from "./ui";

export type SortKey = "name" | "ip" | "presence" | "last_seen" | "open_ports";
export type Sort = { key: SortKey; dir: "asc" | "desc" };

const ipValue = (ip: string) =>
  ip.split(".").reduce((n, part) => n * 256 + (Number(part) || 0), 0);
const presenceRank: Record<string, number> = {
  offline: 0,
  suspected_missing: 1,
  unknown: 2,
  online: 3,
};
const sortValue: Record<SortKey, (d: Row) => string | number> = {
  name: (d) => label(d).toLowerCase(),
  ip: (d) => ipValue(d.ip),
  presence: (d) => (d.monitored ? (presenceRank[d.presence] ?? 2) : 4),
  last_seen: (d) => d.last_seen || 0,
  open_ports: (d) => d.open_ports || 0,
};
export function sortDevices(items: Row[], { key, dir }: Sort) {
  const value = sortValue[key];
  return [...items].sort((a, b) => {
    const x = value(a),
      y = value(b);
    const order = x < y ? -1 : x > y ? 1 : ipValue(a.ip) - ipValue(b.ip);
    return dir === "asc" ? order : -order;
  });
}

export const staleExplanation =
  "Stale: evidence is older than three discovery intervals or the network is unhealthy. Presence shown is the last known state, not a new observation.";

export function PresenceCell({ device: d }: { device: Row }) {
  return (
    <span className="presence-cell">
      <Badge state={d.monitored ? d.presence : "not_monitored"} />
      {d.stale && (
        <span className="stale-tag" title={staleExplanation}>
          <Clock3 size={12} aria-hidden="true" />
          Stale
        </span>
      )}
    </span>
  );
}

export function Flags({ device: d }: { device: Row }) {
  const flags = [
    needsReview(d) && (
      <span className="flag review" key="review">
        Needs review
      </span>
    ),
    d.watched && (
      <span className="flag" key="watched">
        <Eye size={12} aria-hidden="true" /> Watched
      </span>
    ),
    isMuted(d) && (
      <span
        className="flag"
        key="muted"
        title={`Muted until ${time(d.mute_until)}`}
      >
        <BellOff size={12} aria-hidden="true" /> Muted
      </span>
    ),
    d.archived && (
      <span className="flag" key="archived">
        <Archive size={12} aria-hidden="true" /> Archived
      </span>
    ),
  ].filter(Boolean);
  return flags.length ? <span className="flags">{flags}</span> : null;
}

export function DeviceTable({
  items,
  sort,
  onSort,
  empty = "No devices match this view.",
}: {
  items: Row[];
  sort?: Sort;
  onSort?: (key: SortKey) => void;
  empty?: ReactNode;
}) {
  const actions = useDeviceActions();
  if (!items.length) return <Empty>{empty}</Empty>;
  const header = (key: SortKey, text: string, className = "") => {
    const active = sort?.key === key;
    return (
      <th
        className={className}
        aria-sort={
          active ? (sort.dir === "asc" ? "ascending" : "descending") : undefined
        }
      >
        {onSort ? (
          <button className="sort" onClick={() => onSort(key)}>
            {text}
            {active ? (
              sort.dir === "asc" ? (
                <ArrowUp size={12} aria-hidden="true" />
              ) : (
                <ArrowDown size={12} aria-hidden="true" />
              )
            ) : (
              <ArrowUpDown size={12} aria-hidden="true" className="idle" />
            )}
          </button>
        ) : (
          text
        )}
      </th>
    );
  };
  return (
    <>
      {(actions.status || actions.error) && (
        <div className="table-status">
          <ErrorBox error={actions.error} />
          {actions.status && (
            <Status>
              <Check size={15} aria-hidden="true" /> {actions.status}
            </Status>
          )}
        </div>
      )}
      <div className="table-scroll">
        <table className="device-table">
          <thead>
            <tr>
              {header("name", "Device")}
              {header("ip", "IP address", "wide-only")}
              {header("presence", "Presence")}
              {header("last_seen", "Last seen", "wide-only")}
              {header("open_ports", "Open ports", "wide-only")}
              <th className="actions-column">
                <span className="sr-only">Quick actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((d) => (
              <tr key={d.id} className={d.archived ? "archived" : ""}>
                <td>
                  <a className="device-name" href={`/devices/${d.id}`}>
                    <span className="device-icon" aria-hidden="true">
                      <Server size={18} />
                    </span>
                    <span>
                      <strong>{label(d)}</strong>
                      <small>
                        <span className="narrow-only">{d.ip} · </span>
                        {d.mac || "No MAC · provisional identity"}
                        {d.vendor && (
                          <span className="wide-only"> · {d.vendor}</span>
                        )}
                      </small>
                    </span>
                  </a>
                  <Flags device={d} />
                </td>
                <td className="wide-only">
                  <code>{d.ip}</code>
                </td>
                <td>
                  <PresenceCell device={d} />
                  <small className="narrow-only">
                    Seen <When at={d.last_seen} />
                  </small>
                </td>
                <td className="wide-only">
                  <When at={d.last_seen} />
                </td>
                <td className="wide-only">
                  <span className="port-count">{d.open_ports}</span>
                </td>
                <td className="row-actions">
                  {needsReview(d) && (
                    <button
                      className="small"
                      aria-label={`Acknowledge ${label(d)}`}
                      onClick={() =>
                        actions.update(
                          d.id,
                          { acknowledged: true },
                          `${label(d)} acknowledged`,
                        )
                      }
                    >
                      <Check size={14} aria-hidden="true" />
                      <span className="wide-only">Acknowledge</span>
                    </button>
                  )}
                  <button
                    className={`small icon-toggle${d.watched ? " on" : ""}`}
                    aria-pressed={!!d.watched}
                    aria-label={`Watch ${label(d)}`}
                    title={
                      d.watched
                        ? "Watched: presence changes can notify. Click to stop watching."
                        : "Watch: notify when this device goes offline"
                    }
                    onClick={() =>
                      actions.update(
                        d.id,
                        { watched: !d.watched },
                        d.watched
                          ? `Stopped watching ${label(d)}`
                          : `Watching ${label(d)}`,
                      )
                    }
                  >
                    {d.watched ? (
                      <Eye size={15} aria-hidden="true" />
                    ) : (
                      <EyeOff size={15} aria-hidden="true" />
                    )}
                    <span className="wide-only">Watch</span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
