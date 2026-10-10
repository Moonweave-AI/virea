export interface RoomSnapshot {
  stage: string;
  direction?: string;
  target?: "auto" | "ai" | "observer";
  same_instance?: boolean;
  error?: string | null;
}
export function roomView(state: RoomSnapshot | null, offline?: boolean): {
  visible: boolean; active: boolean; text: string;
};
