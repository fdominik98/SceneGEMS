import { useEffect, useRef, useState } from "react";
import type { CampaignEvent } from "../../domain/cluster/schemas";
import { formatClock, formatDateTime, splitClassId } from "../campaigns/campaignFormat";
import { eventDetails, eventLabel, eventTone } from "./campaignModel";
import { ToneBadge } from "./campaignParts";

const NEAR_BOTTOM_PX = 40;

function EventRow({ event }: { event: CampaignEvent }) {
  const details = eventDetails(event);
  return (
    <li className="camp-event">
      <time className="camp-event-time" dateTime={event.at} title={formatDateTime(event.at)}>
        {formatClock(event.at)}
      </time>
      <ToneBadge tone={eventTone(event.kind)}>{eventLabel(event.kind)}</ToneBadge>
      <span className="camp-event-body">
        {event.fec_id && (
          <span className="camp-event-class" title={event.fec_id}>
            {splitClassId(event.fec_id).name}
          </span>
        )}
        {details.map((detail) => (
          <span key={detail.key} className="camp-event-detail">
            <span className="camp-event-key">{detail.key}</span> {detail.value}
          </span>
        ))}
      </span>
      <span className="camp-event-id" title="Event id">
        {event.event_id}
      </span>
    </li>
  );
}

/** The campaign's events from the oldest to the newest; the feed follows the newest while it is scrolled to the end. */
export function EventsFeed({ events, live }: { events: readonly CampaignEvent[]; live: boolean }) {
  const listRef = useRef<HTMLOListElement | null>(null);
  const [following, setFollowing] = useState(true);
  const newest = events.length > 0 ? events[events.length - 1].event_id : 0;

  useEffect(() => {
    const list = listRef.current;
    if (list && following) {
      list.scrollTop = list.scrollHeight;
    }
  }, [newest, following]);

  const onScroll = () => {
    const list = listRef.current;
    if (list) {
      setFollowing(list.scrollHeight - list.scrollTop - list.clientHeight < NEAR_BOTTOM_PX);
    }
  };

  return (
    <section className="camp-events" aria-label="Events">
      <p className="meta">
        {events.length} {events.length === 1 ? "event" : "events"}, oldest first, {live ? "pushed live" : "polled every 4 s"}
      </p>
      {events.length === 0 ? (
        <p className="meta">No events yet.</p>
      ) : (
        <ol className="camp-event-list" ref={listRef} onScroll={onScroll} tabIndex={0} aria-label="Campaign events">
          {events.map((event) => (
            <EventRow key={event.event_id} event={event} />
          ))}
        </ol>
      )}
      {!following && events.length > 0 && (
        <button type="button" className="camp-jump" onClick={() => setFollowing(true)}>
          Jump to the newest
        </button>
      )}
    </section>
  );
}
