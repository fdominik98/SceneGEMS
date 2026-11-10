import { useCallback, useMemo, useSyncExternalStore } from "react";
import { useSelectedCluster } from "./clusterStore";
import type { LiveChannelStatus } from "./liveChannel";
import { getLiveChannel } from "./liveChannels";
import { rawTopicReducer, type LiveTopicReducer, type RawTopicState } from "./liveTopics";
import { IDLE_TOPIC_STATE, LiveTopicWatcher, type LiveTopicState } from "./liveTopicWatcher";

const noopSubscribe = () => () => {};
const idleState = () => IDLE_TOPIC_STATE;

/**
 * Follows a topic of the selected cluster's live channel. Components that follow the same
 * topic share one subscription. Pass a module-level reducer from `liveTopics.ts`
 * (`workerNodesReducer`, `campaignReducer`, `jobReducer`, `instanceReducer`); without one the
 * state is the raw snapshot and the latest updates. A null topic follows nothing.
 */
export function useLiveTopic(topic: string | null): LiveTopicState<RawTopicState>;
export function useLiveTopic<T>(topic: string | null, reducer: LiveTopicReducer<T>): LiveTopicState<T>;
export function useLiveTopic<T>(
  topic: string | null,
  reducer: LiveTopicReducer<T> = rawTopicReducer as unknown as LiveTopicReducer<T>
): LiveTopicState<T> {
  const operatorUrl = useSelectedCluster()?.operatorUrl ?? null;
  const watcher = useMemo(
    () => (operatorUrl && topic ? new LiveTopicWatcher(getLiveChannel(operatorUrl), topic, reducer) : null),
    [operatorUrl, topic, reducer]
  );
  return useSyncExternalStore(watcher ? watcher.subscribe : noopSubscribe, watcher ? watcher.getState : idleState);
}

/** The status of a cluster's live channel ("idle" without a cluster). */
export function useLiveChannelStatus(operatorUrl: string | null): LiveChannelStatus {
  const channel = useMemo(() => (operatorUrl ? getLiveChannel(operatorUrl) : null), [operatorUrl]);
  const subscribe = useCallback((listener: () => void) => (channel ? channel.onStatusChange(listener) : () => {}), [channel]);
  const getStatus = useCallback((): LiveChannelStatus => (channel ? channel.getStatus() : "idle"), [channel]);
  return useSyncExternalStore(subscribe, getStatus);
}
