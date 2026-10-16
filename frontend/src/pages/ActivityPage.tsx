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
} from "../components/ui";
export function ActivityPage() {
  const p = new URLSearchParams(location.search),
    [category, setCategory] = useState(p.get("category") || ""),
    [q, setQ] = useState(p.get("q") || ""),
    [offset, setOffset] = useOffset();
  const { data, error } = useData(
    `/events?category=${category}&device_id=${p.get("device_id") || ""}&offset=${offset}&q=${encodeURIComponent(q)}`,
  );
  return (
    <>
      <Heading
        eyebrow="CHANGE HISTORY"
        title="The story behind the state."
        description="Presence, identity, and service observations, with their evidence intact."
      />
      <div className="tabs">
        {[
          ["", "All activity"],
          ["presence", "Presence"],
          ["ports", "Ports & services"],
          ["identity", "Identity"],
          ["system", "Scanner"],
        ].map(([value, text]) => (
          <button
            className={category === value ? "selected" : ""}
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
          <Search size={17} />
          <input
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
        <Pager total={data?.total || 0} offset={offset} setOffset={setOffset} />
      </Panel>
    </>
  );
}
