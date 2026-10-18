import type { ComponentType, ReactNode } from "react";
import {
  Clock3,
  Database,
  Network,
  Radar,
  Eye,
  ChevronRight,
  ArrowDownLeft,
  TriangleAlert,
} from "lucide-react";
import {
  Heading,
  useData,
  useAllDevices,
  Panel,
  Empty,
  ErrorBox,
  Events,
  When,
  Row,
  ago,
  now,
  time,
  isMissing,
  needsReview,
} from "../components/ui";
import { DeviceTable } from "../components/DeviceTable";
import { BaselineCallout } from "../components/Baseline";

const minutes = (seconds: number) =>
  seconds % 60 ? `${seconds}s` : `${seconds / 60} min`;

function Tile({
  href,
  name,
  value,
  caption,
  Icon,
  tone = "",
}: {
  href: string;
  name: string;
  value: string | number;
  caption: ReactNode;
  Icon: ComponentType<{ size?: number }>;
  tone?: string;
}) {
  return (
    <a className={`stat ${tone}`} href={href}>
      <div>
        <span>{name}</span>
        <span aria-hidden="true">
          <Icon size={18} />
        </span>
      </div>
      <strong>{value}</strong>
      <small>{caption}</small>
    </a>
  );
}

// The scanner tile answers "can I trust what I'm looking at?"
function scannerState(data: Row, networks: Row[], lastPorts?: number) {
  const enabled = networks.filter((n) => n.enabled);
  const last = Math.max(0, ...enabled.map((n) => n.last_discovery || 0));
  const live = enabled.some((n) => n.mode === "live");
  const workerUp = data.worker && data.worker.expires > now();
  const unhealthy = enabled.find((n) => n.health !== "healthy");
  const cadence = `discovery every ${minutes(data.discovery_seconds)}, ports every ${minutes(data.ports_seconds)}`;
  const seen = (
    <>
      Discovery <When at={last || null} />
      {lastPorts ? (
        <>
          {" "}
          · ports <When at={lastPorts} />
        </>
      ) : null}
    </>
  );
  if (!enabled.length)
    return {
      value: "Idle",
      tone: "amber",
      caption: "No network is being monitored",
      detail: "Add or enable a network in Settings.",
    };
  if (!last)
    return {
      value: "Waiting",
      tone: "amber",
      caption: "No discovery yet",
      detail: `Expected ${cadence}.`,
    };
  if (live && !workerUp)
    return {
      value: "Worker down",
      tone: "red",
      caption: seen,
      detail:
        "The scan worker isn't reporting. Presence stays last known until it returns.",
    };
  if (unhealthy)
    return {
      value: "Attention",
      tone: "amber",
      caption: seen,
      detail: `${unhealthy.name}: ${unhealthy.health_reason}`,
    };
  if (now() - last > data.discovery_seconds * 3)
    return {
      value: "Stale",
      tone: "amber",
      caption: seen,
      detail: `No discovery since ${time(last)} (${ago(last)}), expected ${cadence}. Presence is last known; stale evidence never marks devices offline.`,
    };
  return { value: "Fresh", tone: "green", caption: seen, detail: "" };
}

export function Overview() {
  const { data, error, isPending } = useData("/overview");
  const inventory = useAllDevices(),
    scans = useData("/scans?limit=20"),
    // Asked of the server: filtering six recent events here can leave none.
    presence = useData("/events?category=presence&baseline=false&limit=6");
  if (isPending) return <Empty>Loading network overview…</Empty>;
  if (!data) return <ErrorBox error={error} />;
  const counts = data.counts,
    networks: Row[] = data.networks,
    devices = inventory.data || [];
  const fixture =
    networks.length > 0 && networks.every((n) => n.mode === "fixture");
  const lastPorts = (scans.data?.runs.items as Row[] | undefined)?.find(
    (r) => r.kind !== "discovery",
  )?.observed_at;
  const scanner = scannerState(data, networks, lastPorts);
  const missing = counts.offline + counts.suspected_missing;
  // Missing devices first (watched ones on top), then unreviewed arrivals.
  const attention = devices
    .filter((d) => !d.archived && (isMissing(d) || needsReview(d)))
    .sort(
      (a, b) =>
        Number(isMissing(b)) - Number(isMissing(a)) ||
        Number(b.watched) - Number(a.watched) ||
        (b.first_seen || 0) - (a.first_seen || 0),
    );
  const changes: Row[] = presence.data?.items || [];
  const single = networks.length === 1 ? networks[0] : null;
  return (
    <>
      <Heading
        eyebrow="NETWORK AT A GLANCE"
        title={single ? single.name : "Your network"}
        description={
          single ? (
            <>
              <code>{single.cidr}</code> · {counts.total} devices known ·{" "}
              {single.mode === "live" ? "live scanning" : "fixture data"}
            </>
          ) : (
            `${counts.total} devices across ${networks.length} networks`
          )
        }
      />
      {fixture && (
        <div className="notice">
          <Database size={17} aria-hidden="true" />
          <span>
            <strong>Fixture workspace</strong> · Saved Nmap observations. No
            live network is being scanned.
          </span>
          <a href="/settings">
            Configuration <ChevronRight size={14} aria-hidden="true" />
          </a>
        </div>
      )}
      {!networks.length && (
        <div className="notice">
          Start by importing a saved Nmap fixture using the CLI, or configure an
          authorized live scope in Settings.
        </div>
      )}
      {networks
        .filter((n) => n.baseline && n.enabled)
        .map((n) => (
          <BaselineCallout key={n.id} network={n} devices={devices} />
        ))}
      <div className="stats">
        <Tile
          href="/devices?view=online"
          name="Online now"
          value={counts.online}
          caption={
            <>
              of {counts.total} devices
              {counts.unknown ? ` · ${counts.unknown} unknown` : ""}
              {counts.unmonitored
                ? ` · ${counts.unmonitored} not monitored`
                : ""}
            </>
          }
          Icon={Network}
          tone="green"
        />
        <Tile
          href="/devices?view=missing"
          name="Offline or missing"
          value={missing}
          caption={
            missing
              ? `${counts.offline} offline · ${counts.suspected_missing} suspected missing`
              : "Nothing has gone missing"
          }
          Icon={ArrowDownLeft}
          tone={missing ? "red" : ""}
        />
        <Tile
          href="/devices?view=review"
          name="Needs review"
          value={counts.awaiting_review}
          caption={
            counts.awaiting_review
              ? "New or not yet acknowledged"
              : "Everything is acknowledged"
          }
          Icon={Eye}
          tone={counts.awaiting_review ? "amber" : ""}
        />
        <Tile
          href="/scans"
          name="Scanner"
          value={scanner.value}
          caption={scanner.caption}
          Icon={Radar}
          tone={scanner.tone}
        />
      </div>
      {scanner.detail && (
        <div className="notice warning" role="status">
          <TriangleAlert size={17} aria-hidden="true" />
          <span>
            <strong>Scanner {scanner.value.toLowerCase()}</strong> ·{" "}
            {scanner.detail}
          </span>
          <a href="/scans">
            Scans <ChevronRight size={14} aria-hidden="true" />
          </a>
        </div>
      )}
      <Panel
        title="Needs attention"
        subtitle={
          attention.length
            ? "Missing devices first, then new or unacknowledged ones."
            : undefined
        }
        action={
          <a className="text-link" href="/devices">
            All {counts.total} devices <ChevronRight size={15} />
          </a>
        }
      >
        {inventory.isPending ? (
          <Empty>Loading devices…</Empty>
        ) : (
          <DeviceTable
            items={attention.slice(0, 8)}
            empty={
              <>
                <strong>Nothing needs you.</strong>
                <p>
                  All {counts.total} devices are acknowledged and none are
                  missing.
                </p>
              </>
            }
          />
        )}
        {attention.length > 8 && (
          <p className="panel-footnote">
            <a className="text-link" href="/devices?view=review">
              {attention.length - 8} more <ChevronRight size={13} />
            </a>
          </p>
        )}
      </Panel>
      <div className="two-column">
        <Panel
          title="Presence changes"
          subtitle="Arrivals, absences, and recoveries"
          action={
            <a className="text-link" href="/activity?category=presence">
              History <ChevronRight size={14} />
            </a>
          }
        >
          <Events
            items={changes}
            compact
            empty={
              data.presence.length
                ? "No arrivals or outages since the baseline was recorded."
                : "No presence changes recorded yet."
            }
          />
        </Panel>
        <Panel
          title="Port & service changes"
          subtitle="Kept as history. Never a notification."
          action={
            <a className="text-link" href="/activity?category=ports">
              History <ChevronRight size={14} />
            </a>
          }
        >
          <Events
            items={data.ports}
            compact
            empty="No port or service changes since the first scan."
          />
        </Panel>
      </div>
      <div className="observation-note">
        <Clock3 size={15} aria-hidden="true" /> Polling captures observations,
        not continuous activity. Changes between scans may be missed.
      </div>
    </>
  );
}
