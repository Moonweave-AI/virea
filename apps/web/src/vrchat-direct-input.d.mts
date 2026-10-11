export type DirectState = {
  head_yaw: number; head_pitch: number; pointer_x: number; pointer_y: number;
  head_x: number; head_y: number; head_z: number;
  left_hand: number[]; right_hand: number[];
  view_aspect: number; horizontal_fov: number; calibration: boolean;
  projection_center_x: number; projection_center_y: number;
  trigger: boolean; trigger_left: boolean; vertical: number; horizontal: number; turn: number;
  run: boolean; jump: boolean; grab: boolean; drop: boolean; grab_left: boolean; drop_left: boolean;
  scroll_x: number; scroll_y: number; move_hold: number;
};
type Rect = {left: number; top: number; width: number; height: number};
export function imageBounds(rect: Rect, width: number, height: number): Rect | null;
export function imagePoint(rect: Rect, width: number, height: number, x: number, y: number): Pick<DirectState, "pointer_x" | "pointer_y"> | null;
export class DirectInput {
  constructor(initial?: Partial<DirectState>);
  state: DirectState;
  target: "head" | "left" | "right";
  enqueue(command?: string | null): void;
  next(): {state: DirectState; command: string | null};
  aim(point: Pick<DirectState, "pointer_x" | "pointer_y">, aspect: number): void;
  look(dx: number, dy: number): void;
  pointer(down: boolean, left?: boolean): void;
  wheel(dx: number, dy: number, shift?: boolean, control?: boolean): void;
  advance(seconds: number): void;
  reset(): void;
  release(): void;
  key(code: string, down: boolean, repeat?: boolean): boolean | "release";
}
