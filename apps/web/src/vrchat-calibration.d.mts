export type CalibrationSnapshot = {
  stage: string; active?: boolean; step?: number; total_steps?: number; percent?: number;
  completed_at?: number | null; error?: string | null; step_label?: string; detail?: string | null;
};
export function calibrationView(state?: CalibrationSnapshot | null, offline?: boolean): {
  visible: boolean; active?: boolean; complete?: boolean; percent?: number; step?: number;
  total?: number; label?: string; title?: string; count?: string; detail?: string;
  failed?: boolean; offline?: boolean;
};
