export type Turn = {role: "user" | "assistant"; content: string};
export type Conversation = {id: string; title: string; sessionId: string | null; updatedAt: number; messages: Turn[]};
export function mergeTranscript(previous: Turn[], current: Turn[]): Turn[];
export function readConversations(raw: string | null): Conversation[];
export function bridgeError(state: any): string;
export function executionResult(state: any): {status: string; motion_seconds: number | null} | null;
export function statusLabel(state: any): string;
