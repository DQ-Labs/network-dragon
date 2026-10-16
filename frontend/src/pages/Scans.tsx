import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { write } from "../api/client";
import { Radar } from "lucide-react";
import {
  Heading,
  useData,
  Panel,
  Empty,
  ErrorBox,
  Badge,
  time,
  Row,
  Pager,
  useOffset,
} from "../components/ui";
export function Scans() {
  const [offset, setOffset] = useOffset();
  const { data, error } = useData(`/scans?offset=${offset}`),
    networks = useData("/networks"),
    profiles = useData("/scan-profiles"),
    settings = useData("/settings");
  const [err, setErr] = useState<Error | null>(null),
    query = useQueryClient();
  return (
    <>
      <Heading
        eyebrow="SCANNER OPERATIONS"
        title="Evidence you can inspect."
        description="Discovery establishes presence. TCP scans capture services independently."
      />
      <ErrorBox error={error || err} />
      <Panel
        title="Queue a scan"
        subtitle="Execution is performed by the worker, within the installation allowlist."
      >
        <form
          className="form inline-form"
          onSubmit={async (e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            try {
              await write("/scans", "POST", Object.fromEntries(f));
              setErr(null);
              query.invalidateQueries();
            } catch (e) {
              setErr(e as Error);
            }
          }}
        >
          <label>
            Network
            <select name="network_id" required>
              {((networks.data as unknown as Row[]) || [])
                .filter((n) => n.mode === "live")
                .map((n) => (
                  <option key={n.id} value={n.id}>
                    {n.name}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Profile
            <select name="profile_id">
              {((profiles.data as unknown as Row[]) || []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Numeric target
            <input
              name="target"
              required
              placeholder="Configured address or CIDR"
            />
          </label>
          <button className="primary" disabled={!settings.data?.live_scanning}>
            <Radar size={16} />
            Queue scan
          </button>
        </form>
        {!settings.data?.live_scanning && (
          <p className="panel-footnote">
            Live scanning is disabled. Configure authorized scope and interface
            in the installation TOML before enabling it.
          </p>
        )}
      </Panel>
      <Panel
        title="Job queue"
        subtitle="One scan process at a time; discovery has priority."
      >
        {data?.jobs.items.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Target</th>
                  <th>Profile</th>
                  <th>Status</th>
                  <th>Requested</th>
                  <th>Action / diagnostic</th>
                </tr>
              </thead>
              <tbody>
                {data.jobs.items.map((j: Row) => (
                  <tr key={j.id}>
                    <td>
                      <code>{j.target}</code>
                    </td>
                    <td>{j.profile_id}</td>
                    <td>
                      <Badge state={j.status} />
                    </td>
                    <td>{time(j.created_at)}</td>
                    <td>
                      {["queued", "running"].includes(j.status) ? (
                        <button
                          onClick={async () => {
                            await write(`/scans/${j.id}/cancel`, "POST");
                            query.invalidateQueries();
                          }}
                        >
                          Cancel
                        </button>
                      ) : (
                        j.error || "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No queued jobs. Fixture imports appear below.</Empty>
        )}
      </Panel>
      <Panel
        title="Scan evidence"
        subtitle="Saved coverage, provenance, and health classification."
      >
        {data?.runs.items.length ? (
          <div className="run-list">
            {data.runs.items.map((r: Row) => (
              <details key={r.id}>
                <summary>
                  <span className="run-icon">
                    <Radar size={18} />
                  </span>
                  <strong>
                    {r.kind === "discovery" ? "Discovery" : "TCP ports"}
                  </strong>
                  <span className="pill">{r.source}</span>
                  <code>{r.coverage.targets}</code>
                  <Badge state={r.status} />
                  <time>{time(r.observed_at)}</time>
                </summary>
                <div className="run-detail">
                  <p>
                    {r.health_reason || "Complete, parseable scan evidence"}
                  </p>
                  <p>
                    Nmap {r.version} · Profile {r.profile_revision} ·{" "}
                    {r.coverage.ports.length} TCP ports covered
                  </p>
                  <code>
                    {r.coverage.ports.join(", ") ||
                      "Discovery only — no port coverage"}
                  </code>
                  <small>Scan ID: {r.id}</small>
                </div>
              </details>
            ))}
          </div>
        ) : (
          <Empty>No scan evidence imported yet.</Empty>
        )}
        <Pager
          total={Math.max(data?.runs.total || 0, data?.jobs.total || 0)}
          offset={offset}
          setOffset={setOffset}
        />
      </Panel>
    </>
  );
}
