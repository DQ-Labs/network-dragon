import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Search, Check } from "lucide-react";
import { write } from "../api/client";
import {
  Heading,
  Panel,
  Empty,
  ErrorBox,
  param,
  label,
  isMuted,
  isMissing,
  needsReview,
  useAllDevices,
  type Row,
} from "../components/ui";
import {
  DeviceTable,
  sortDevices,
  type Sort,
  type SortKey,
} from "../components/DeviceTable";

const views: [string, string, (d: Row) => boolean][] = [
  ["", "All", (d) => !d.archived],
  ["review", "Needs review", needsReview],
  [
    "online",
    "Online",
    (d) => !d.archived && d.monitored && d.presence === "online",
  ],
  ["missing", "Offline or missing", (d) => !d.archived && isMissing(d)],
  [
    "unknown",
    "Unknown",
    (d) => !d.archived && d.monitored && d.presence === "unknown",
  ],
  ["stale", "Stale", (d) => !d.archived && d.stale],
  ["watched", "Watched", (d) => !d.archived && d.watched],
  ["muted", "Muted", (d) => !d.archived && isMuted(d)],
  ["archived", "Archived", (d) => d.archived],
];
const sortKeys = ["name", "ip", "presence", "last_seen", "open_ports"];

export function Devices() {
  const params = new URLSearchParams(location.search);
  const [q, setQ] = useState(params.get("q") || ""),
    [view, setView] = useState(
      views.some(([key]) => key === params.get("view"))
        ? params.get("view")!
        : "",
    ),
    [sort, setSort] = useState<Sort>({
      key: (sortKeys.includes(params.get("sort") || "")
        ? params.get("sort")
        : "ip") as SortKey,
      dir: params.get("dir") === "desc" ? "desc" : "asc",
    });
  const { data, error, isPending } = useAllDevices(),
    archived = useAllDevices(true);
  const search = useRef<HTMLInputElement>(null);
  useEffect(() => {
    // "/" jumps to the search box from anywhere on the page.
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        e.key === "/" &&
        !["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
      ) {
        e.preventDefault();
        search.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  const devices = [...(data || []), ...(archived.data || [])];
  const term = q.trim().toLowerCase();
  const matches = devices.filter(
    (d) =>
      !term ||
      [label(d), d.hostname, d.ip, d.mac, d.vendor, d.notes].some((v) =>
        String(v || "")
          .toLowerCase()
          .includes(term),
      ),
  );
  const shown = sortDevices(
    matches.filter(views.find(([key]) => key === view)![2]),
    sort,
  );
  return (
    <>
      <Heading
        eyebrow="INVENTORY"
        title="Devices"
        description="Find a device, check its presence, and act on it. Press / to search."
      />
      <div className="toolbar">
        <label className="search">
          <Search size={17} aria-hidden="true" />
          <input
            ref={search}
            type="search"
            aria-label="Search devices"
            placeholder="Search name, IP, MAC, vendor, or notes…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              param("q", e.target.value);
            }}
          />
        </label>
      </div>
      <div className="chips" role="group" aria-label="Show devices">
        {views.map(([key, text, test]) => {
          const count = matches.filter(test).length;
          if (
            !count &&
            key &&
            key !== view &&
            !["review", "missing"].includes(key)
          )
            return null;
          return (
            <button
              key={key}
              className={`chip${key === "review" && count ? " attention" : ""}`}
              aria-pressed={view === key}
              onClick={() => {
                setView(key);
                param("view", key);
              }}
            >
              {text}
              <span className="chip-count">{count}</span>
            </button>
          );
        })}
      </div>
      <ErrorBox error={error || archived.error} />
      <Panel
        title={views.find(([key]) => key === view)![1] + " devices"}
        subtitle={
          data
            ? `Showing ${shown.length} of ${devices.filter((d) => !d.archived).length} active devices${term ? ` matching “${q.trim()}”` : ""}`
            : "Loading…"
        }
        action={
          view === "review" && shown.length > 0 ? (
            <AcknowledgeAll devices={shown} />
          ) : undefined
        }
      >
        {isPending ? (
          <Empty>Loading devices…</Empty>
        ) : (
          <DeviceTable
            items={shown}
            sort={sort}
            onSort={(key) => {
              const next: Sort = {
                key,
                dir: sort.key === key && sort.dir === "asc" ? "desc" : "asc",
              };
              setSort(next);
              param("sort", next.key);
              param("dir", next.dir);
            }}
            empty={
              view === "review" && !term
                ? "Every device is acknowledged. New arrivals will show up here."
                : term
                  ? `No devices match “${q.trim()}” in this view.`
                  : "No devices in this view."
            }
          />
        )}
      </Panel>
    </>
  );
}

function AcknowledgeAll({ devices }: { devices: Row[] }) {
  const [confirming, setConfirming] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<Error | null>(null),
    query = useQueryClient();
  if (!confirming)
    return (
      <div className="panel-actions">
        <button className="small" onClick={() => setConfirming(true)}>
          <Check size={14} aria-hidden="true" />
          Acknowledge all {devices.length}…
        </button>
      </div>
    );
  return (
    <div
      className="panel-actions"
      role="group"
      aria-label="Confirm acknowledging devices"
    >
      <span className="muted">
        Acknowledge {devices.length} device{devices.length === 1 ? "" : "s"}?
      </span>
      <button
        className="small primary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            for (const d of devices)
              await write(`/devices/${d.id}`, "PATCH", { acknowledged: true });
            setError(null);
          } catch (e) {
            setError(e as Error);
          } finally {
            setBusy(false);
            setConfirming(false);
            query.invalidateQueries();
          }
        }}
      >
        {busy ? "Acknowledging…" : "Acknowledge"}
      </button>
      <button className="small" autoFocus onClick={() => setConfirming(false)}>
        Cancel
      </button>
      <ErrorBox error={error} />
    </div>
  );
}
