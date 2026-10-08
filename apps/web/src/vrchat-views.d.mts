export type FrameInfo = {pid: string; sequence: string; width: string; height: string};
export function viewError(code: string): string;
export class FramePump {
  constructor(role: "observer" | "ai", onFrame: (blob: Blob, info: FrameInfo) => void, onStatus: (message: string) => void, fetcher?: typeof fetch);
  start(): void;
  stop(): void;
}
