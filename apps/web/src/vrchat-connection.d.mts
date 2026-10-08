export function connectionView(state: any, offline?: boolean): {title: string; detail: string; avatar: string; ready: boolean; steps: [string, boolean][]};
export function readConnectionSettings(raw: string | null): {version: number; fields: Record<string, string | boolean>; wanted?: boolean} | null;
