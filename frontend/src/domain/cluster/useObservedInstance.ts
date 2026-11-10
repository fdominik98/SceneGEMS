import { useCallback, useMemo, useState, useSyncExternalStore } from "react";
import { useSelectedCluster } from "./clusterStore";
import { getLiveChannel } from "./liveChannels";
import type { SubscribeOptions } from "./liveProtocol";
import { instanceReducer, type InstanceTopicState } from "./liveTopics";
import { IDLE_TOPIC_STATE, LiveTopicWatcher, type LiveTopicState } from "./liveTopicWatcher";

const noopSubscribe = () => () => {};
const idleState = () => IDLE_TOPIC_STATE;

export interface ObservedInstance {
  state: LiveTopicState<InstanceTopicState>;
  /** Changes the options of the observed topic (a simulation's speed). */
  configure: (options: SubscribeOptions) => void;
}

/**
 * Follows one `instance:` topic of the selected cluster and keeps it subscribed only while
 * the component is mounted with a topic, so the control node observes the instance only while it
 * is viewed. `options` are sent with the `subscribe` of the topic as it was when the topic
 * was chosen; later changes go through `configure`. A null topic follows nothing.
 */
export function useObservedInstance(topic: string | null, options?: SubscribeOptions): ObservedInstance {
  const operatorUrl = useSelectedCluster()?.operatorUrl ?? null;
  const [initialOptions] = useState(options);
  const watcher = useMemo(
    () => (operatorUrl && topic ? new LiveTopicWatcher(getLiveChannel(operatorUrl), topic, instanceReducer, initialOptions) : null),
    [operatorUrl, topic, initialOptions]
  );
  const state = useSyncExternalStore(watcher ? watcher.subscribe : noopSubscribe, watcher ? watcher.getState : idleState);
  const configure = useCallback((next: SubscribeOptions) => watcher?.configure(next), [watcher]);
  return { state, configure };
}
