export interface Position { x: number; y: number; z: number }
export interface BodyState {
  position: Position;
  yaw: number;
  pose: Record<string, [number, number, number, number]>;
  gaze_target: string | null;
  behavior: string;
}
export interface SceneAction {
  kind: "look_at" | "move_to" | "stop";
  target_id: string | null;
  position: Position | null;
}
export interface Expression {
  id: string;
  epoch: number;
  text: string;
  actions: SceneAction[];
  audio_url: string | null;
  audio_seconds: number;
  motion: { vrma_url: string; result_id: string } | null;
}
export interface FaceTrack { fps: number; names: string[]; values: number[][] }
export interface Session {
  id: string;
  epoch: number;
  status: string;
  body: BodyState;
  pending: Expression | null;
  events: { sequence: number; kind: string; message?: string }[];
  history: { role: string; content: string }[];
  metrics: { first_expression_seconds: number | null; rtf: number | null };
}
