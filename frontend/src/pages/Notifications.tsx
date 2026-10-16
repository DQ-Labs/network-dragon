import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { write } from "../api/client";
import { ShieldCheck } from "lucide-react";
import {
  Heading,
  useData,
  Panel,
  Empty,
  ErrorBox,
  Badge,
  time,
  Pager,
  useOffset,
  Row,
} from "../components/ui";
export function Notifications() {
  const [actionError, setActionError] = useState<Error | null>(null);
  const [offset, setOffset] = useOffset(),
    { data, error } = useData(`/notifications?offset=${offset}`),
    settings = useData("/settings"),
    query = useQueryClient();
  return (
    <>
      <Heading
        eyebrow="PRESENCE NOTIFICATIONS"
        title="Attention, where it belongs."
        description="New arrivals and watched-device outages. A quiet record of everything else."
      />
      <div className="policy-banner">
        <ShieldCheck size={28} />
        <div>
          <strong>Port and service changes never notify.</strong>
          <p>
            No port alerts, service-version messages, or change digests. Service
            history stays available in Activity.
          </p>
        </div>
        <span className="pill">Always history-only</span>
      </div>
      <div className="two-column">
        <Panel title="Delivery policy">
          <div className="policy-list">
            <div>
              New devices after baseline<span>Eligible</span>
            </div>
            <div>
              Watched device offline<span>Eligible</span>
            </div>
            <div>
              Watched device recovered<span>Only after accepted outage</span>
            </div>
            <div>
              Port / service changes<span>Never</span>
            </div>
          </div>
        </Panel>
        <Panel
          title="Delivery controls"
          subtitle={
            settings.data?.credentials_configured
              ? "Pushover credentials configured on the server."
              : "Pushover credentials are not configured."
          }
        >
          <div className="form">
            <Badge
              state={
                settings.data?.notifications && !settings.data?.delivery_paused
                  ? "enabled"
                  : "disabled"
              }
            />
            <p>
              Events suppressed by baseline, mute, or cooldown are not replayed.
            </p>
            <button
              onClick={async () => {
                await write("/notifications/pause", "POST", {
                  paused: !settings.data?.delivery_paused,
                });
                query.invalidateQueries();
              }}
            >
              {settings.data?.delivery_paused
                ? "Resume future delivery"
                : "Pause delivery"}
            </button>
            <small>
              Explicit test delivery is available after server credentials and
              delivery are enabled.
            </small>
            <button
              disabled={
                !settings.data?.notifications ||
                !settings.data?.credentials_configured
              }
              onClick={async () => {
                try {
                  await write("/notifications/test", "POST");
                  query.invalidateQueries();
                  setActionError(null);
                } catch (e) {
                  setActionError(e as Error);
                }
              }}
            >
              Send test notification
            </button>
            {settings.data?.notification_test && (
              <small>
                Last explicit test: {settings.data.notification_test.status} ·{" "}
                {time(settings.data.notification_test.at)}
              </small>
            )}
            <ErrorBox error={actionError} />
          </div>
        </Panel>
      </div>
      <ErrorBox error={error} />
      <Panel
        title="Delivery history"
        subtitle="Suppression reasons and sanitized provider outcomes."
      >
        {data?.items.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Reason</th>
                  <th>Observed</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((n: Row) => (
                  <tr key={n.id}>
                    <td>{n.event.type}</td>
                    <td>
                      <Badge state={n.status} />
                    </td>
                    <td>{n.attempts}</td>
                    <td>{n.reason || "Accepted by provider"}</td>
                    <td>{time(n.event.at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty>No notification delivery records.</Empty>
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
