import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Radar, ArrowDownLeft, ArrowUpRight, Waves } from "lucide-react";
import { api } from "../api/client";
export type Row = Record<string, any>;
export const label = (d: Row) => d.name || d.hostname || d.ip;
export const time = (v?: number) =>
  v ? new Date(v * 1000).toLocaleString() : "Not observed";
export function ago(v?: number) {
  if (!v) return "Never";
  const seconds = Math.max(0, Date.now() / 1000 - v);
  return seconds < 60
    ? "Just now"
    : seconds < 3600
      ? `${Math.floor(seconds / 60)}m ago`
      : seconds < 86400
        ? `${Math.floor(seconds / 3600)}h ago`
        : `${Math.floor(seconds / 86400)}d ago`;
}

export function Badge({ state }: { state: string }) {
  return (
    <span className={`badge ${state}`}>
      <span />
      {state.replaceAll("_", " ")}
    </span>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty">
      <Radar size={28} />
      <p>{children}</p>
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

export function Panel({
  title,
  subtitle,
  children,
  action,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="panel">
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

export function Events({
  items = [],
  compact = false,
}: {
  items: Row[];
  compact?: boolean;
}) {
  if (!items.length)
    return (
      <Empty>No changes recorded yet. New observations will appear here.</Empty>
    );
  return (
    <div className="events">
      {items.map((e) => (
        <a
          className="event"
          href={e.device_id ? `/devices/${e.device_id}` : "/scans"}
          key={e.id}
        >
          <span
            className={`event-icon ${e.type.startsWith("port") || e.type.startsWith("service") ? "quiet" : ""}`}
          >
            {e.type.includes("offline") ? (
              <ArrowDownLeft size={17} />
            ) : e.type.startsWith("port") || e.type.startsWith("service") ? (
              <Waves size={17} />
            ) : (
              <ArrowUpRight size={17} />
            )}
          </span>
          <span className="event-body">
            <strong>
              {e.type.replaceAll(".", " · ").replaceAll("_", " ")}
              {e.facts.port ? ` · TCP ${e.facts.port}` : ""}
            </strong>
            <span>
              {e.facts.ip ||
                e.facts.reason ||
                (e.facts.after?.state
                  ? `${e.facts.before?.state || "unobserved"} → ${e.facts.after.state}`
                  : e.facts.after && typeof e.facts.after === "string"
                    ? e.facts.after.replaceAll("_", " ")
                    : "Observation recorded")}
              {e.baseline ? " · baseline" : ""}
            </span>
            {!compact && <code>{JSON.stringify(e.facts)}</code>}
          </span>
          <time title={time(e.at)}>{ago(e.at)}</time>
        </a>
      ))}
    </div>
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
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
