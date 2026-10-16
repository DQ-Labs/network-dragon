import { Server, Eye } from "lucide-react";
import { type Row, Empty, Badge, label, time, ago } from "./ui";
export function DeviceTable({ items }: { items: Row[] }) {
  if (!items.length) return <Empty>No devices match this view.</Empty>;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Device</th>
            <th>IP address</th>
            <th>Presence</th>
            <th>Last seen</th>
            <th>Open ports</th>
            <th>Watch</th>
          </tr>
        </thead>
        <tbody>
          {items.map((d) => (
            <tr key={d.id}>
              <td>
                <a className="device-name" href={`/devices/${d.id}`}>
                  <span className="device-icon">
                    <Server size={18} />
                  </span>
                  <span>
                    <strong>{label(d)}</strong>
                    <small>
                      {d.mac || "Provisional identity"}
                      {!d.acknowledged && (
                        <span
                          className="review-dot"
                          title="Awaiting acknowledgement"
                        />
                      )}
                    </small>
                  </span>
                </a>
              </td>
              <td>
                <code>{d.ip}</code>
              </td>
              <td>
                <Badge state={!d.monitored ? "not_monitored" : d.presence} />
                {d.stale && <span className="stale">stale evidence</span>}
              </td>
              <td>
                <span title={time(d.last_seen)}>{ago(d.last_seen)}</span>
              </td>
              <td>
                <span className="port-count">{d.open_ports}</span>
              </td>
              <td>
                {d.watched ? (
                  <span className="watch">
                    <Eye size={16} /> Watched
                  </span>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
