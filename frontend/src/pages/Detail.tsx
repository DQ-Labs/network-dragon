import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { write } from "../api/client";
import { Clock3, Check, ChevronRight } from "lucide-react";
import {
  Heading,
  useData,
  Panel,
  Empty,
  ErrorBox,
  Events,
  Badge,
  label,
  time,
  ago,
  Pager,
  Row,
} from "../components/ui";
export function Detail({ id }: { id: string }) {
  const [portOffset, setPortOffset] = useState(0);
  const { data: d, error } = useData(`/devices/${id}`),
    ports = useData(`/devices/${id}/ports?limit=50&offset=${portOffset}`),
    events = useData(`/events?device_id=${id}`);
  const query = useQueryClient(),
    [err, setErr] = useState<Error | null>(null),
    [saved, setSaved] = useState(false);
  async function update(body: Row) {
    try {
      await write(`/devices/${id}`, "PATCH", body);
      await query.invalidateQueries();
      setSaved(true);
    } catch (e) {
      setErr(e as Error);
    }
  }
  if (!d)
    return error ? <ErrorBox error={error} /> : <Empty>Loading device…</Empty>;
  return (
    <>
      <a className="text-link" href="/devices">
        ← Device inventory
      </a>
      <Heading
        eyebrow={`${d.confidence.toUpperCase()} IDENTITY`}
        title={label(d)}
        description={`${d.ip} · ${d.mac || "MAC unavailable — lower identity confidence"}`}
        action={<Badge state={d.monitored ? d.presence : "not_monitored"} />}
      />
      {d.stale && (
        <div className="notice">
          <Clock3 size={17} /> Last-known state · discovery evidence is stale.
          Last seen {time(d.last_seen)}.
        </div>
      )}
      <ErrorBox error={err} />
      <div className="two-column detail-grid">
        <Panel
          title="Device details"
          subtitle="Annotations don't change discovery identity."
        >
          <form
            className="form"
            key={d.id}
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              update({ name: f.get("name"), notes: f.get("notes") });
            }}
          >
            <label>
              Display name
              <input name="name" defaultValue={d.name} maxLength={120} />
            </label>
            <label>
              Notes
              <textarea name="notes" defaultValue={d.notes} maxLength={4000} />
            </label>
            <div className="button-row">
              <button className="primary">Save details</button>
              {saved && (
                <span className="success">
                  <Check size={16} /> Saved
                </span>
              )}
            </div>
          </form>
          <div className="control-list">
            <label>
              <span>
                Watched device
                <small>Notify on qualifying presence changes</small>
              </span>
              <input
                type="checkbox"
                checked={d.watched}
                onChange={(e) => update({ watched: e.target.checked })}
              />
            </label>
            <label>
              <span>
                Acknowledged<small>Remove the awaiting-review badge</small>
              </span>
              <input
                type="checkbox"
                checked={d.acknowledged}
                onChange={(e) => update({ acknowledged: e.target.checked })}
              />
            </label>
            <div className="button-row">
              <button
                onClick={() =>
                  update({
                    mute_until:
                      d.mute_until && d.mute_until > Date.now() / 1000
                        ? null
                        : Date.now() / 1000 + 3600,
                  })
                }
              >
                {d.mute_until && d.mute_until > Date.now() / 1000
                  ? "Unmute"
                  : "Mute for 1 hour"}
              </button>
              <button onClick={() => update({ archived: !d.archived })}>
                {d.archived ? "Unarchive" : "Archive"}
              </button>
            </div>
          </div>
        </Panel>
        <Panel
          title="Last-known TCP ports"
          subtitle="Unscanned ports are never assumed closed."
        >
          {ports.data?.items.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Port</th>
                    <th>State</th>
                    <th>Service evidence</th>
                    <th>Observed</th>
                  </tr>
                </thead>
                <tbody>
                  {ports.data.items.map((p: Row) => (
                    <tr key={p.id}>
                      <td>
                        <code>{p.port}/tcp</code>
                      </td>
                      <td>
                        <Badge state={p.state} />
                      </td>
                      <td>
                        {p.facts.name || "Unknown"}
                        <small>
                          {p.facts.method === "probed"
                            ? `Probed · ${p.facts.product || ""} ${p.facts.version || ""}`
                            : "Port-number guess"}
                        </small>
                        {p.facts.service_observed_at && (
                          <small title={time(p.facts.service_observed_at)}>
                            Service evidence: {ago(p.facts.service_observed_at)}
                          </small>
                        )}
                      </td>
                      <td title={time(p.observed_at)}>{ago(p.observed_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty>No port evidence yet.</Empty>
          )}
          <p className="panel-footnote">
            Port and service changes are always history-only.
          </p>
          <Pager
            total={ports.data?.total || 0}
            offset={portOffset}
            limit={ports.data?.limit}
            setOffset={setPortOffset}
          />
        </Panel>
      </div>
      <Panel
        title="Address history"
        subtitle="Bindings retain their original identity evidence."
      >
        <div className="address-list">
          {d.addresses.map((a: Row) => (
            <div key={a.id}>
              <code>{a.address}</code>
              <span>
                {time(a.first_seen)} →{" "}
                {a.ended_at ? time(a.ended_at) : "current binding"}
              </span>
            </div>
          ))}
        </div>
        <details className="settings-details">
          <summary>Administrator-reviewed identity aliases</summary>
          <div className="form">
            <p>
              Original observations remain attached to their original identity.
              An alias stops being monitored independently; the canonical
              identity drives future presence.
            </p>
            {d.canonical_id && (
              <a className="text-link" href={`/devices/${d.canonical_id}`}>
                Open canonical identity
              </a>
            )}
            {d.aliases.map((alias: Row) => (
              <a
                key={alias.id}
                className="text-link"
                href={`/devices/${alias.id}`}
              >
                {label(alias)} · original evidence
              </a>
            ))}
          </div>
          {!d.canonical_id && (
            <form
              className="form"
              onSubmit={async (e) => {
                e.preventDefault();
                try {
                  await write(
                    `/devices/${id}/merge`,
                    "POST",
                    Object.fromEntries(new FormData(e.currentTarget)),
                  );
                  query.invalidateQueries();
                } catch (e) {
                  setErr(e as Error);
                }
              }}
            >
              <label>
                Canonical device UUID
                <input name="canonical_id" required />
              </label>
              <label>
                Reason for this verified alias
                <input name="reason" required minLength={5} maxLength={500} />
              </label>
              <button>Record alias & stop monitoring this identity</button>
            </form>
          )}
        </details>
      </Panel>
      <Panel
        title="Observation timeline"
        action={
          <a className="text-link" href={`/activity?device_id=${id}`}>
            Full history <ChevronRight size={14} />
          </a>
        }
      >
        <Events items={events.data?.items || []} />
      </Panel>
    </>
  );
}
