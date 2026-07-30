import { useEffect, useRef } from "react";

export function useWebSocket(
  url: string,
  onMessage: (data: string) => void,
  enabled: boolean = true
) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const onMessageRef = useRef(onMessage);

  // Keep the latest callback without triggering effect re-runs
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let isSubscribed = true;

    const connect = () => {
      if (!isSubscribed) return;

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        if (!isSubscribed) return;
        onMessageRef.current(event.data);
      };

      ws.onclose = () => {
        if (!isSubscribed) return;
        // Auto-reconnect after 2 seconds
        reconnectTimeoutRef.current = setTimeout(() => {
          connect();
        }, 2000);
      };

      ws.onerror = (error) => {
        console.error(`WebSocket error for ${url}:`, error);
        ws.close();
      };
    };

    connect();

    return () => {
      isSubscribed = false;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        // Only close if it's not already closed
        if (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING) {
            wsRef.current.close();
        }
      }
    };
  }, [url, enabled]);

  return wsRef;
}
