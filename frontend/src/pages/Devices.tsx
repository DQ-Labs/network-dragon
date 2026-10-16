import { useState } from "react";
import { Search } from "lucide-react";
import {
  Heading,
  useData,
  Panel,
  Empty,
  ErrorBox,
  Pager,
  useOffset,
  param,
} from "../components/ui";
import { DeviceTable } from "../components/DeviceTable";
export function Devices() {
  const params = new URLSearchParams(location.search);
  const [q, setQ] = useState(params.get("q") || ""),
    [presence, setPresence] = useState(params.get("presence") || ""),
    [sort, setSort] = useState(params.get("sort") || "ip");
  const [offset, setOffset] = useOffset();
  const { data, error, isPending } = useData(
    `/devices?q=${encodeURIComponent(q)}&presence=${presence}&sort=${sort}&offset=${offset}`,
  );
  return (
    <>
      <Heading
        eyebrow="INVENTORY"
        title="Every device, in perspective."
        description="Review identity, presence, and the services last observed."
      />
      <div className="toolbar">
        <label className="search">
          <Search size={17} />
          <input
            aria-label="Search devices"
            placeholder="Search name, IP, or MAC…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              param("q", e.target.value);
              setOffset(0);
            }}
          />
        </label>
        <select
          aria-label="Filter presence"
          value={presence}
          onChange={(e) => {
            setPresence(e.target.value);
            param("presence", e.target.value);
            setOffset(0);
          }}
        >
          <option value="">All presence states</option>
          <option value="online">Online</option>
          <option value="suspected_missing">Suspected missing</option>
          <option value="offline">Offline</option>
        </select>
        <select
          aria-label="Sort devices"
          value={sort}
          onChange={(e) => {
            setSort(e.target.value);
            param("sort", e.target.value);
          }}
        >
          <option value="ip">IP address</option>
          <option value="name">Name</option>
          <option value="last_seen">Last seen</option>
        </select>
      </div>
      <ErrorBox error={error} />
      <Panel
        title="Device inventory"
        subtitle={`${data?.total || 0} identities · IPv4 monitoring`}
      >
        {isPending ? (
          <Empty>Loading devices…</Empty>
        ) : (
          <DeviceTable items={data?.items || []} />
        )}
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
