export interface Position { x: number; y: number; z: number }
export interface BodyState {
  position: Position;
  yaw: number;
  pelvis_height?: number;
  pose: Record<string, [number, number, number, number]>;
  gaze_target: string | null;
  behavior: string;
  history?: Omit<BodyState, "history" | "gaze_target" | "behavior">[];
}
export interface GestureWeights { head: number; torso: number; left_arm: number; right_arm: number; hands: number }
export interface BodyProgram { id: string; actions: SceneAction[]; end_state: "hold" | "relaxed"; status: "ready" | "playing" | "completed" | "failed" | "interrupted" }
export interface SceneAction {
  kind: "look_at" | "move_to" | "reach" | "sit" | "stand" | "perform" | "stop";
  target_id: string | null;
  position: Position | null;
  description?: string | null;
  label?: string | null;
  duration_seconds?: number | null;
  transition_description?: string | null;
  continuation_description?: string | null;
  gesture_weights?: GestureWeights;
}
export interface Expression {
  id: string;
  session_id?: string;
  body_program_id?: string;
  epoch: number;
  text: string;
  actions: SceneAction[];
  audio_url: string | null;
  audio_seconds: number;
  motion: { vrma_url: string; result_id: string } | null;
  /** Internal windows continue on one clock; only the final window retracts. */
  continues?: boolean;
  stream_id?: string;
  sequence?: number;
  offset_seconds?: number;
  parent_id?: string | null;
  caption?: string;
  route?: { engine: "sentiavatar" | "ardy" | "hybrid"; reason: string } | null;
  end_state?: "relaxed" | "hold";
  preview?: boolean;
}
export interface FaceTrack { fps: number; names: string[]; values: number[][];
  arkit?: { names: string[]; values: number[][] } }
export interface PlaybackProgress {
  elapsed: number; audioDuration: number; motionDuration: number; paused: boolean;
}
export interface Session {
  id: string;
  epoch: number;
  status: string;
  body: BodyState;
  pending: Expression | null;
  buffered: Expression | null;
  ready?: Expression[];
  latest_expression: Expression | null;
  draft_text: string;
  route?: Expression["route"];
  body_program?: BodyProgram | null;
  motion_plan?: SceneAction[];
  playback_mode: "voice_first" | "synchronized";
  events: { sequence: number; kind: string; message?: string; text?: string;
    interrupted?: boolean; feedback?: { status: string } }[];
  history: { role: string; content: string }[];
  metrics: { first_expression_seconds: number | null; rtf: number | null;
    first_audio_seconds: number | null; language_seconds: number | null;
    tts_seconds: number | null; motion_seconds: number | null };
}
