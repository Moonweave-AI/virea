export function clientLaunchView(state: any, role: "observer" | "ai", offline?: boolean, busy?: boolean): {
  label: string; detail: string; account: string; progress: number; step: number; total: number;
  active: boolean; showProgress: boolean; ready: boolean; startDisabled: boolean; restartDisabled: boolean; startText: string;
};
