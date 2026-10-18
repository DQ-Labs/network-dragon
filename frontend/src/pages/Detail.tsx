import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { write } from "../api/client";
import {
  Clock3,
  Check,
  ChevronRight,
  Eye,
  EyeOff,
  BellOff,
  Bell,
  Archive,
  ArchiveRestore,
} from "lucide-react";
import {
  Heading,
  useData,
  useAllDevices,
  useDeviceActions,
  Panel,
  Empty,
  ErrorBox,
  Events,
  Badge,
  Status,
  When,
  label,
  time,
  now,
  isMuted,
  needsReview,
  Pager,
  Row,
} from "../components/ui";
import {
  Flags,
  PresenceCell,
  staleExplanation,
} from "../components/DeviceTable";

const muteChoices: [string, number][] = [
  ["1 hour", 3600],
  ["8 hours", 8 * 3600],
  ["24 hours", 86400],
  ["7 days", 7 * 86400],
];

export function Detail({ id }: { id: string }) {
  const [portOffset, setPortOffset] = useState(0);
  const { data: d, error } = useData(`/devices/${id}`),
    ports = useData(`/devices/${id}/ports?limit=50&offset=${portOffset}`),
    events = useData(`/events?device_id=${id}`),
    networks = useData("/networks"),
    all = useAllDevices();
  const query = useQueryClient(),
    actions = useDeviceActions(),
    [mergeError, setMergeError] = useState<Error | null>(null);
  if (!d)
    return error ? <ErrorBox error={error} /> : <Empty>Loading device…</Empty>;
  const name = label(d),
    muted = isMuted(d),
    update = (body: Row, message: string) => actions.update(id, body, message);
  const network = ((networks.data as unknown as Row[]) || []).find(
    (n) => n.id === d.network_id,
  );
  const mergeTargets = (all.data || []).filter(
    (other) =>
      other.id !== d.id &&
      other.network_id === d.network_id &&
      !other.canonical_id,
  );
  return (
    <>
      <a className="text-link back-link" href="/devices">
        ← All devices
      </a>
      <Heading
        eyebrow={`${d.confidence.toUpperCase()} IDENTITY${network ? ` · ${network.name.toUpperCase()}` : ""}`}
        title={name}
        description={`${d.ip} · ${d.mac || "MAC unavailable, lower identity confidence"}`}
        action={<PresenceCell device={d} />}
      />
      <div className="device-flags">
        <Flags device={d} />
        {d.canonical_id && (
          <a className="text-link" href={`/devices/${d.canonical_id}`}>
            Alias: open canonical identity <ChevronRight size={13} />
          </a>
        )}
      </div>
      {d.stale && (
        <div className="notice" title={staleExplanation}>
          <Clock3 size={17} aria-hidden="true" /> Last-known state · discovery
          evidence is stale. Last seen {time(d.last_seen)}.
        </div>
      )}
      <div className="action-bar" role="group" aria-label="Device actions">
        {needsReview(d) ? (
          <button
            className="primary"
            onClick={() =>
              update({ acknowledged: true }, `${name} acknowledged`)
            }
          >
            <Check size={16} aria-hidden="true" /> Acknowledge
          </button>
        ) : (
          <button
            aria-pressed={!!d.acknowledged}
            title="Acknowledged. Click to mark as awaiting review again."
            onClick={() =>
              update(
                { acknowledged: !d.acknowledged },
                d.acknowledged
                  ? `${name} marked as awaiting review`
                  : `${name} acknowledged`,
              )
            }
          >
            <Check size={16} aria-hidden="true" /> Acknowledged
          </button>
        )}
        <button
          aria-pressed={!!d.watched}
          title="Watched devices can notify when they go offline or recover."
          onClick={() =>
            update(
              { watched: !d.watched },
              d.watched ? `Stopped watching ${name}` : `Watching ${name}`,
            )
          }
        >
          {d.watched ? (
            <Eye size={16} aria-hidden="true" />
          ) : (
            <EyeOff size={16} aria-hidden="true" />
          )}
          {d.watched ? "Watching" : "Watch"}
        </button>
        {muted ? (
          <button
            title={`Muted until ${time(d.mute_until)}`}
            onClick={() => update({ mute_until: null }, `${name} unmuted`)}
          >
            <Bell size={16} aria-hidden="true" /> Unmute
            <span className="button-note">
              until <When at={d.mute_until} />
            </span>
          </button>
        ) : (
          <details className="menu">
            <summary className="button">
              <BellOff size={16} aria-hidden="true" /> Mute…
            </summary>
            <div className="menu-list" role="group" aria-label="Mute for">
              {muteChoices.map(([text, seconds]) => (
                <button
                  key={text}
                  onClick={(e) => {
                    e.currentTarget.closest("details")!.open = false;
                    update(
                      { mute_until: now() + seconds },
                      `${name} muted for ${text}`,
                    );
                  }}
                >
                  Mute for {text}
                </button>
              ))}
            </div>
          </details>
        )}
        <button
          onClick={() =>
            update(
              { archived: !d.archived },
              d.archived ? `${name} restored` : `${name} archived`,
            )
          }
          title={
            d.archived
              ? "Restore this device to the inventory and monitoring"
              : "Hide this device from the inventory and stop monitoring it"
          }
        >
          {d.archived ? (
            <ArchiveRestore size={16} aria-hidden="true" />
          ) : (
            <Archive size={16} aria-hidden="true" />
          )}
          {d.archived ? "Unarchive" : "Archive"}
        </button>
        {actions.status && (
          <Status>
            <Check size={16} aria-hidden="true" /> {actions.status}
          </Status>
        )}
      </div>
      <ErrorBox error={actions.error} />
      <div className="two-column detail-grid">
        <Panel
          title="Identity & notes"
          subtitle="Your name and notes don't change discovery identity."
        >
          <dl className="facts">
            <div>
              <dt>Hostname</dt>
              <dd>{d.hostname || "Not reported"}</dd>
            </div>
            <div>
              <dt>IP address</dt>
              <dd>
                <code>{d.ip}</code>
              </dd>
            </div>
            <div>
              <dt>MAC address</dt>
              <dd>
                <code>{d.mac || "Unavailable"}</code>
              </dd>
            </div>
            <div>
              <dt>Vendor</dt>
              <dd>{d.vendor || "Not reported"}</dd>
            </div>
            <div>
              <dt>First seen</dt>
              <dd>
                <When at={d.first_seen} />
              </dd>
            </div>
            <div>
              <dt>Last seen</dt>
              <dd>
                <When at={d.last_seen} />
              </dd>
            </div>
            <div>
              <dt>Open ports</dt>
              <dd>{d.open_ports}</dd>
            </div>
          </dl>
          <form
            className="form"
            key={d.id}
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              update(
                { name: f.get("name"), notes: f.get("notes") },
                "Name and notes saved",
              );
            }}
          >
            <label>
              Display name
              <input
                name="name"
                defaultValue={d.name}
                maxLength={120}
                placeholder={d.hostname || d.ip}
              />
            </label>
            <label>
              Notes
              <textarea
                name="notes"
                defaultValue={d.notes}
                maxLength={4000}
                placeholder="Owner, location, purpose…"
              />
            </label>
            <div className="button-row">
              <button className="primary">Save details</button>
            </div>
          </form>
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
                          <small>
                            Service evidence:{" "}
                            <When at={p.facts.service_observed_at} />
                          </small>
                        )}
                      </td>
                      <td>
                        <When at={p.observed_at} />
                      </td>
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
        title="Observation timeline"
        action={
          <a className="text-link" href={`/activity?device_id=${id}`}>
            Full history <ChevronRight size={14} />
          </a>
        }
      >
        <Events items={events.data?.items || []} showDevice={false} />
      </Panel>
      <Panel
        title="Address history"
        subtitle="Bindings retain their original identity evidence."
      >
        <div className="address-list">
          {d.addresses.map((a: Row) => (
            <div key={a.id}>
              <code>{a.address}</code>
              <span>
                <When at={a.first_seen} /> →{" "}
                {a.ended_at ? <When at={a.ended_at} /> : "current binding"}
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
                  setMergeError(null);
                  query.invalidateQueries();
                } catch (e) {
                  setMergeError(e as Error);
                }
              }}
            >
              <label>
                Canonical device
                <select name="canonical_id" required defaultValue="">
                  <option value="" disabled>
                    Choose the device this is an alias of…
                  </option>
                  {mergeTargets.map((other) => (
                    <option key={other.id} value={other.id}>
                      {label(other)} · {other.ip}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Reason for this verified alias
                <input name="reason" required minLength={5} maxLength={500} />
              </label>
              <ErrorBox error={mergeError} />
              <button>Record alias & stop monitoring this identity</button>
            </form>
          )}
        </details>
      </Panel>
    </>
  );
}
