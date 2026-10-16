import {
  Clock3,
  Database,
  Network,
  Radar,
  Server,
  Eye,
  Bell,
  ChevronRight,
  Activity,
} from "lucide-react";
import {
  Heading,
  useData,
  Panel,
  Empty,
  ErrorBox,
  Events,
  Row,
} from "../components/ui";
import { DeviceTable } from "../components/DeviceTable";
export function Overview() {
  const { data, error, isPending } = useData("/overview");
  const inventory = useData("/devices?limit=6");
  if (isPending) return <Empty>Loading network overview…</Empty>;
  if (!data) return <ErrorBox error={error} />;
  const counts = data.counts,
    networks: Row[] = data.networks;
  const fixture =
    networks.length > 0 && networks.every((n) => n.mode === "fixture");
  const stale = networks.some(
    (n) =>
      !n.last_discovery ||
      Date.now() / 1000 - n.last_discovery > data.discovery_seconds * 3,
  );
  return (
    <>
      <Heading
        eyebrow="NETWORK AT A GLANCE"
        title="A little clarity. A lot less noise."
        description="Know what's here, what changed, and what needs your attention."
        action={
          <a className="button primary" href="/scans">
            <Radar size={17} />
            Review scans
          </a>
        }
      />
      {fixture && (
        <div className="notice">
          <Database size={17} />
          <span>
            <strong>Fixture workspace</strong> · Saved Nmap observations. No
            live network is being scanned.
          </span>
          <a href="/settings">
            Configuration <ChevronRight size={14} />
          </a>
        </div>
      )}
      {!networks.length && (
        <div className="notice">
          Start by importing a saved Nmap fixture using the CLI, or configure an
          authorized live scope in Settings.
        </div>
      )}
      <div className="stats">
        {[
          [
            "Devices online",
            counts.online,
            "Last known presence",
            Network,
            "green",
          ],
          [
            "Devices offline",
            counts.offline,
            "Confirmed absence only",
            Server,
            "",
          ],
          [
            "Awaiting review",
            counts.awaiting_review,
            "Acknowledge your inventory",
            Eye,
            "amber",
          ],
          [
            "Watched devices",
            counts.watched,
            "Presence alerts eligible",
            Bell,
            "",
          ],
        ].map(([name, count, caption, Icon, color]: any) => (
          <section className="stat" key={name}>
            <div>
              <span>{name}</span>
              <Icon size={18} />
            </div>
            <strong className={color}>{count}</strong>
            <small>{caption}</small>
          </section>
        ))}
      </div>
      <div className="health-strip">
        <div className="health-symbol">
          <Radar size={21} />
        </div>
        <div>
          <strong>
            {stale
              ? "Observation data is stale"
              : networks.some((n) => n.health !== "healthy")
                ? "Scanner needs attention"
                : networks.length
                  ? "Discovery evidence available"
                  : "Waiting for first discovery"}
          </strong>
          <span>
            {stale
              ? "Presence is last known. Stale evidence does not make devices offline."
              : "Presence and service monitoring run independently."}
          </span>
        </div>
        <div className="cadence">
          <span>
            DISCOVERY<strong>Every {data.discovery_seconds / 60} min</strong>
          </span>
          <span>
            TCP PORTS<strong>Every {data.ports_seconds / 60} min</strong>
          </span>
        </div>
      </div>
      <Panel
        title="Your devices"
        subtitle="A focused view of the latest inventory"
        action={
          <a className="text-link" href="/devices">
            View all devices <ChevronRight size={15} />
          </a>
        }
      >
        <DeviceTable items={inventory.data?.items || []} />
      </Panel>
      <div className="two-column">
        <Panel
          title="Presence activity"
          subtitle="Arrivals, absences, and recoveries"
          action={
            <span className="panel-icon">
              <Activity size={18} />
            </span>
          }
        >
          <Events items={data.presence} compact />
        </Panel>
        <Panel
          title="Quiet service history"
          subtitle="Useful changes. Never a Pushover notification."
          action={<span className="pill">History only</span>}
        >
          <Events items={data.ports} compact />
        </Panel>
      </div>
      <div className="observation-note">
        <Clock3 size={15} /> Polling captures observations, not continuous
        activity. Changes between scans may be missed.
      </div>
    </>
  );
}
