/**
 * The line between a project window and its pop-out detail window: one
 * BroadcastChannel per project, `plm2-project-<id>`. The main window posts
 * the selected part and revision; the pop-out announces itself with hello
 * and leaves with bye.
 */
import { useCallback, useEffect, useRef } from 'react';

export type SelectionMessage =
  | { type: 'select'; partId: number | null; revisionId: number | null }
  | { type: 'ping' }
  | { type: 'hello' }
  | { type: 'bye' };

export function selectionChannelSupported(): boolean {
  return typeof BroadcastChannel !== 'undefined';
}

export function selectionChannelName(projectId: number): string {
  return `plm2-project-${projectId}`;
}

export function useSelectionChannel(
  projectId: number,
  onMessage: (message: SelectionMessage) => void,
  farewell?: SelectionMessage,
): (message: SelectionMessage) => void {
  const channelRef = useRef<BroadcastChannel | null>(null);
  const handlerRef = useRef(onMessage);
  const farewellRef = useRef(farewell);
  useEffect(() => {
    handlerRef.current = onMessage;
    farewellRef.current = farewell;
  });

  useEffect(() => {
    if (!projectId || !selectionChannelSupported()) return;
    const channel = new BroadcastChannel(selectionChannelName(projectId));
    channel.onmessage = (event: MessageEvent) => handlerRef.current(event.data as SelectionMessage);
    channelRef.current = channel;
    const sayGoodbye = () => {
      if (farewellRef.current) channel.postMessage(farewellRef.current);
    };
    // A closing window does not unmount React; pagehide is the last word it gets.
    window.addEventListener('pagehide', sayGoodbye);
    return () => {
      window.removeEventListener('pagehide', sayGoodbye);
      sayGoodbye();
      channel.close();
      if (channelRef.current === channel) channelRef.current = null;
    };
  }, [projectId]);

  return useCallback((message: SelectionMessage) => {
    channelRef.current?.postMessage(message);
  }, []);
}
