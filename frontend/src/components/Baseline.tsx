import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck, ChevronRight } from "lucide-react";
import { write } from "../api/client";
import { ErrorBox, Row, When, needsReview } from "./ui";

export function FinishBaseline({ network }: { network: Row }) {
  const [confirming, setConfirming] = useState(false),
    [error, setError] = useState<Error | null>(null),
    query = useQueryClient();
  const blocked =
    network.health !== "healthy" || !network.last_discovery
      ? `Needs a healthy discovery first: ${network.health_reason}`
      : "";
  if (confirming)
    return (
      <div
        className="confirm"
        role="group"
        aria-label={`Confirm finishing baseline review for ${network.name}`}
      >
        <p>
          Start delivery for new devices and watched-device outages on{" "}
          {network.name}? Baseline events are not replayed. Port and service
          changes still never notify.
        </p>
        <div className="button-row">
          <button
            className="primary"
            onClick={async () => {
              try {
                await write(`/networks/${network.id}`, "PATCH", {
                  activate_notifications: true,
                });
                setConfirming(false);
                query.invalidateQueries();
              } catch (e) {
                setError(e as Error);
              }
            }}
          >
            Finish review & enable delivery
          </button>
          <button autoFocus onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </div>
        <ErrorBox error={error} />
      </div>
    );
  return (
    <div className="finish">
      <button
        disabled={!!blocked}
        onClick={() => {
          setError(null);
          setConfirming(true);
        }}
      >
        Finish baseline review…
      </button>
      {blocked && <small>{blocked}</small>}
    </div>
  );
}

// Step-by-step guidance shown while a network is still in baseline review.
export function BaselineCallout({
  network,
  devices,
}: {
  network: Row;
  devices: Row[];
}) {
  const own = devices.filter((d) => d.network_id === network.id && !d.archived);
  const awaiting = own.filter(needsReview).length,
    watched = own.filter((d) => d.watched).length;
  return (
    <section className="callout" aria-labelledby={`baseline-${network.id}`}>
      <span className="callout-icon" aria-hidden="true">
        <ClipboardCheck size={20} />
      </span>
      <div className="callout-body">
        <h2 id={`baseline-${network.id}`}>
          Baseline review in progress · {network.name}
        </h2>
        <p>
          Notifications are held while you confirm what normally lives on this
          network.
        </p>
        <ol className="steps">
          <li className={network.last_discovery ? "done" : ""}>
            Let discovery run. Last discovery:{" "}
            <When at={network.last_discovery} />
          </li>
          <li className={own.length && !awaiting ? "done" : ""}>
            Acknowledge your fixed devices.{" "}
            {awaiting ? (
              <a className="text-link" href="/devices?view=review">
                {awaiting} awaiting review <ChevronRight size={13} />
              </a>
            ) : (
              "All acknowledged."
            )}
          </li>
          <li className={watched ? "done" : ""}>
            Watch the devices whose outages matter.{" "}
            <a className="text-link" href="/devices?view=watched">
              {watched} watched <ChevronRight size={13} />
            </a>
          </li>
          <li>Finish the review to start presence notifications.</li>
        </ol>
      </div>
      <FinishBaseline network={network} />
    </section>
  );
}
