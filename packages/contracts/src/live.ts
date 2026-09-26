/** F-018: a project's live room — who is here, where they point, when the model changes. */

import type { Vec3 } from "./operation-plan.js";

export interface LiveMember {
  session: string;
  user_id: string;
  name: string;
  colour: string;
}

export interface LiveHead {
  version_id: string;
  sequence_no: number;
  label: string | null;
  created_by: string | null;
}

export type LiveEvent =
  | { type: "welcome"; you: LiveMember; members: LiveMember[]; head: LiveHead | null }
  | { type: "join"; session: string; member: LiveMember }
  | { type: "leave"; session: string }
  | { type: "cursor"; session: string; point: Vec3 | null; body: string | null }
  | { type: "note"; session: string; member: LiveMember; text: string; point: Vec3 | null; at: string }
  | ({ type: "version" } & LiveHead)
  | { type: "pong" }
  | { type: "error"; message: string };

const PING_MS = 20_000;
const CURSOR_MS = 100; // ten updates a second: smooth to watch, well under the room's limit
const MAX_BACKOFF_MS = 15_000;

/**
 * One connection to one room, kept open: it reconnects with backoff after a drop, pings so
 * the server keeps showing you as present, and sends at most ten pointer updates a second
 * (the latest one wins; the ones in between are nobody's business).
 */
export class LiveRoom {
  private socket: WebSocket | null = null;
  private closed = false;
  private backoff = 1000;
  private pinger: ReturnType<typeof setInterval> | null = null;
  private cursorTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingCursor: { point: Vec3 | null; body: string | null } | null = null;

  constructor(
    private readonly url: string,
    private readonly token: string,
    private readonly onEvent: (event: LiveEvent) => void,
    private readonly onStatus: (connected: boolean) => void = () => undefined,
  ) {
    this.connect();
  }

  private connect(): void {
    if (this.closed) return;
    const socket = new WebSocket(this.url);
    this.socket = socket;
    socket.onopen = () => {
      socket.send(JSON.stringify({ type: "hello", token: this.token }));
      this.backoff = 1000;
      this.onStatus(true);
      this.pinger = setInterval(() => this.send({ type: "ping" }), PING_MS);
    };
    socket.onmessage = (message) => {
      try {
        this.onEvent(JSON.parse(String(message.data)) as LiveEvent);
      } catch {
        // a malformed frame is dropped; the room carries on
      }
    };
    socket.onclose = (event) => {
      if (this.pinger) clearInterval(this.pinger);
      this.pinger = null;
      this.onStatus(false);
      // 4401/4403: not allowed in this room — retrying would only knock on the same door.
      if (this.closed || event.code === 4401 || event.code === 4403) return;
      setTimeout(() => this.connect(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
    };
  }

  private send(message: object): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(message));
  }

  pointAt(point: Vec3 | null, body: string | null = null): void {
    this.pendingCursor = { point, body };
    if (this.cursorTimer) return;
    this.cursorTimer = setTimeout(() => {
      this.cursorTimer = null;
      if (this.pendingCursor) this.send({ type: "cursor", ...this.pendingCursor });
      this.pendingCursor = null;
    }, CURSOR_MS);
  }

  note(text: string, point: Vec3 | null = null): void {
    this.send({ type: "note", text, point });
  }

  close(): void {
    this.closed = true;
    if (this.pinger) clearInterval(this.pinger);
    if (this.cursorTimer) clearTimeout(this.cursorTimer);
    this.socket?.close();
  }
}

/** The room's WebSocket URL for an API base URL (http -> ws, https -> wss). */
export function liveUrl(baseUrl: string, projectId: string): string {
  const url = new URL(`${baseUrl.replace(/\/+$/, "")}/api/v1/projects/${projectId}/live`);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}
