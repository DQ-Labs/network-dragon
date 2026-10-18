import { useState } from "react";
import { Search } from "lucide-react";
import {
  Heading,
  useData,
  Panel,
  ErrorBox,
  Events,
  Pager,
  useOffset,
  param,
  label,
  useAllDevices,
} from "../components/ui";
export function ActivityPage() {
  const p = new URLSearchParams(location.search),
    [category, setCategory] = useState(p.get("category") || ""),
    [q, setQ] = useState(p.get("q") || ""),
    [offset, setOffset] = useOffset(),
    deviceId = p.get("device_id") || "",
    devices = useAllDevices();
  const { data, error } = useData(
    `/events?category=${category}&device_id=${deviceId}&offset=${offset}&q=${encodeURIComponent(q)}`,
  );
  const device = devices.data?.find((d) => d.id === deviceId);
  return (
    <>
      <Heading
        eyebrow="CHANGE HISTORY"
        title="Activity"
        description="The story behind the state: presence, identity, and service observations, with their evidence intact."
      />
      {deviceId && (
        <div className="notice">
          <span>
            Showing history for{" "}
            <a className="text-link" href={`/devices/${deviceId}`}>
              {device ? label(device) : "one device"}
            </a>
          </span>
          <a href="/activity">Show all devices</a>
        </div>
      )}
      <div className="tabs" role="group" aria-label="Event category">
        {[
          ["", "All activity"],
          ["presence", "Presence"],
          ["ports", "Ports & services"],
          ["identity", "Identity"],
          ["system", "Scanner"],
        ].map(([value, text]) => (
          <button
            className={category === value ? "selected" : ""}
            aria-pressed={category === value}
            key={value}
            onClick={() => {
              setCategory(value);
              param("category", value);
              setOffset(0);
            }}
          >
            {text}
          </button>
        ))}
      </div>
      <div className="toolbar">
        <label className="search">
          <Search size={17} aria-hidden="true" />
          <input
            type="search"
            aria-label="Search event evidence"
            placeholder="Search port, service, version, address, or event…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              param("q", e.target.value);
              setOffset(0);
            }}
          />
        </label>
      </div>
      <ErrorBox error={error} />
      <Panel
        title={
          category === "ports"
            ? "Quiet port & service history"
            : "Recorded events"
        }
        subtitle="Baseline observations are marked. Port changes never generate notifications."
      >
        <Events items={data?.items || []} />
        <Pager
          total={data?.total || 0}
          offset={offset}
          limit={data?.limit}
          setOffset={setOffset}
        />
      </Panel>
    </>
  );
}
