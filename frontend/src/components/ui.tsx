import { useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Radar,
  ArrowDownLeft,
  ArrowUpRight,
  Waves,
  Fingerprint,
  Activity,
} from "lucide-react";
import { api, write } from "../api/client";
export type Row = Record<string, any>;
export const label = (d: Row) => d.name || d.hostname || d.ip;
export const now = () => Date.now() / 1000;
export const time = (v?: number | null) =>
  v ? new Date(v * 1000).toLocaleString() : "Not observed";
function span(seconds: number) {
  return seconds < 3600
    ? `${Math.max(1, Math.round(seconds / 60))}m`
    : seconds < 86400
      ? `${Math.floor(seconds / 3600)}h`
      : `${Math.floor(seconds / 86400)}d`;
}
export function ago(v?: number | null) {
  if (!v) return "Never";
  const seconds = now() - v;
  if (seconds < 0) return `in ${span(-seconds)}`;
  if (seconds < 45) return "just now";
  if (seconds > 30 * 86400) return new Date(v * 1000).toLocaleDateString();
  return `${span(seconds)} ago`;
}

// Relative time for scanning, exact local time on hover and in the markup.
export function When({
  at,
  empty = "Never",
}: {
  at?: number | null;
  empty?: string;
}) {
  if (!at) return <span className="muted">{empty}</span>;
  return (
    <time dateTime={new Date(at * 1000).toISOString()} title={time(at)}>
      {ago(at)}
    </time>
  );
}

export const sentence = (value: string) => {
  const text = value.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

export function Badge({ state, text }: { state: string; text?: string }) {
  return (
    <span className={`badge ${state}`}>
      <span aria-hidden="true" />
      {text ?? sentence(state)}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty">
      <Radar size={28} aria-hidden="true" />
      <div>{children}</div>
    </div>
  );
}

export function ErrorBox({ error }: { error: Error | null }) {
  return error ? (
    <div role="alert" className="error">
      {error.message}
    </div>
  ) : null;
}

export function useData(path: string) {
  return useQuery<Row>({ queryKey: [path], queryFn: () => api(path) });
}

// One VLAN holds at most 256 addresses, so the whole inventory is small
// enough to load once and filter, sort, and count in the browser. The
// server leaves archived devices out; they are loaded only where shown.
export function useAllDevices(archived = false) {
  return useQuery<Row[]>({
    queryKey: ["/devices", archived ? "archived" : "active"],
    queryFn: async () => {
      const items: Row[] = [];
      for (let offset = 0; offset < 2000;) {
        const page = await api(
          `/devices?sort=ip&limit=100&offset=${offset}${archived ? "&archived=true" : ""}`,
        );
        items.push(...page.items);
        offset += page.limit;
        if (!page.items.length || offset >= page.total) break;
      }
      return items;
    },
  });
}

// Event and delivery history still names devices that were archived since.
export function useDeviceNames() {
  const active = useAllDevices(),
    archived = useAllDevices(true);
  return new Map(
    [...(active.data || []), ...(archived.data || [])].map((d) => [
      d.id,
      label(d),
    ]),
  );
}

export const isMuted = (d: Row) => !!d.mute_until && d.mute_until > now();
export const needsReview = (d: Row) => !d.acknowledged && !d.archived;
export const isMissing = (d: Row) =>
  d.monitored && ["offline", "suspected_missing"].includes(d.presence);

export function useDeviceActions() {
  const query = useQueryClient(),
    [error, setError] = useState<Error | null>(null),
    [status, setStatus] = useState(""),
    timer = useRef<number>(undefined);
  async function update(id: string, body: Row, message: string) {
    try {
      await write(`/devices/${id}`, "PATCH", body);
      setError(null);
      setStatus(message);
      clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setStatus(""), 5000);
      await query.invalidateQueries();
    } catch (e) {
      setError(e as Error);
      setStatus("");
    }
  }
  return { update, error, status };
}

export function Status({ children }: { children: ReactNode }) {
  return (
    <span className="success" role="status">
      {children}
    </span>
  );
}

const eventTitles: Record<string, string> = {
  "device.new": "New device",
  "presence.online": "Came online",
  "presence.offline": "Went offline",
  "presence.recovered": "Back online",
  "presence.suspected_missing": "Suspected missing",
  "port.state": "Port state changed",
  "port.baseline": "Port recorded in baseline",
  "service.changed": "Service changed",
  "identity.address": "Address changed",
  "identity.hostname": "Hostname changed",
  "identity.merged": "Identity merged",
  "scanner.health": "Scanner health changed",
};
export const isQuiet = (type: string) =>
  type.startsWith("port") || type.startsWith("service");

export function eventTitle(e: Row) {
  const base = eventTitles[e.type] || sentence(e.type.replaceAll(".", " "));
  return e.facts?.port ? `${base} · ${e.facts.port}/tcp` : base;
}

export function eventSummary(e: Row): string {
  const f = e.facts || {};
  if (e.type === "port.state")
    return `${f.before?.state || "unobserved"} → ${f.after?.state}${f.after?.name ? ` · ${f.after.name}` : ""}`;
  if (e.type === "port.baseline")
    return `${f.after?.state || "observed"} · ${f.after?.name || "unknown service"}`;
  if (e.type === "service.changed")
    return Object.entries(f.changes || {})
      .map(([k, v]: [string, any]) => `${k} ${v.before} → ${v.after}`)
      .join(", ");
  if (e.type === "device.new")
    return [f.ip, f.mac].filter(Boolean).join(" · ") || "First observation";
  if (e.type === "scanner.health")
    return [f.state && sentence(f.state), f.reason].filter(Boolean).join(" · ");
  if (typeof f.after === "string")
    return `${sentence(f.before || "unknown")} → ${sentence(f.after)}${f.misses ? ` after ${f.misses} missed scans` : ""}`;
  return f.reason || f.ip || "Observation recorded";
}

export function Events({
  items = [],
  compact = false,
  showDevice = true,
  empty = "No changes recorded yet. New observations will appear here.",
}: {
  items: Row[];
  compact?: boolean;
  showDevice?: boolean;
  empty?: ReactNode;
}) {
  const names = useDeviceNames();
  if (!items.length) return <Empty>{empty}</Empty>;
  return (
    <ul className="events">
      {items.map((e) => {
        const quiet = isQuiet(e.type),
          down =
            e.type.includes("offline") || e.type.includes("suspected_missing");
        return (
          <li className="event" key={e.id}>
            <span
              className={`event-icon${quiet ? " quiet" : ""}${down ? " down" : ""}`}
              aria-hidden="true"
            >
              {down ? (
                <ArrowDownLeft size={17} />
              ) : quiet ? (
                <Waves size={17} />
              ) : e.type.startsWith("identity") ? (
                <Fingerprint size={17} />
              ) : e.type.startsWith("scanner") ? (
                <Activity size={17} />
              ) : (
                <ArrowUpRight size={17} />
              )}
            </span>
            <div className="event-body">
              <span className="event-title">
                {!showDevice ? null : e.device_id ? (
                  <a href={`/devices/${e.device_id}`}>
                    {names.get(e.device_id) || e.facts?.ip || "Device"}
                  </a>
                ) : e.type.startsWith("scanner") ? (
                  <a href="/scans">Scanner</a>
                ) : null}
                <strong>{eventTitle(e)}</strong>
              </span>
              <span>
                {eventSummary(e)}
                {e.baseline && <span className="pill">Baseline</span>}
              </span>
              {!compact && (
                <details className="evidence">
                  <summary>Evidence</summary>
                  <code>{JSON.stringify(e.facts, null, 2)}</code>
                </details>
              )}
            </div>
            <When at={e.at} />
          </li>
        );
      })}
    </ul>
  );
}

export function Panel({
  title,
  subtitle,
  children,
  action,
  className = "",
}: {
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-heading">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function Pager({
  total,
  offset,
  limit,
  setOffset,
}: {
  total: number;
  offset: number;
  limit: number | undefined;
  setOffset: (n: number) => void;
}) {
  return (
    <div className="pager">
      <span>
        {limit
          ? total
            ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total}`
            : "0 records"
          : "Loading…"}
      </span>
      <div>
        <button
          disabled={!limit || !offset}
          onClick={() => limit && setOffset(Math.max(0, offset - limit))}
        >
          Previous
        </button>
        <button
          disabled={!limit || offset + limit >= total}
          onClick={() => limit && setOffset(offset + limit)}
        >
          Next
        </button>
      </div>
    </div>
  );
}

export function useOffset() {
  const [offset, update] = useState(
    Math.max(
      0,
      Number(new URLSearchParams(location.search).get("offset")) || 0,
    ),
  );
  return [
    offset,
    (value: number) => {
      update(value);
      param("offset", String(value));
    },
  ] as const;
}

export function param(key: string, value: string) {
  const url = new URL(location.href);
  value ? url.searchParams.set(key, value) : url.searchParams.delete(key);
  history.replaceState(null, "", url);
}

export function Heading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1 tabIndex={-1}>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}
