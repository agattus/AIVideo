export type JobStatus =
  | "queued"
  | "processing"
  | "waiting_for_assets"
  | "completed"
  | "failed";

export type VideoStyle =
  | "cinematic"
  | "documentary"
  | "corporate"
  | "fast_paced_shorts"
  | "animated"
  | "minimal"
  | "suspense";

export type AspectRatio = "16:9" | "9:16" | "1:1";

export interface GeneratePayload {
  idea: string;
  style: VideoStyle;
  aspect_ratio: AspectRatio;
  duration: number;
  max_scenes: number;
  language: string;
  voice: string;
}

export interface GenerateAccepted {
  job_id: string;
  status: JobStatus;
}

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  progress_percent: number;
  current_stage?: string | null;
  error?: string | null;
  run_dir?: string | null;
  download_urls?: Record<string, string> | null;
  title?: string | null;
  idea?: string | null;
  scene_count?: number | null;
}

export interface VoiceOption {
  id: string;
  label: string;
  locale?: string;
  gender?: string;
}

export interface VoiceListResponse {
  voices: VoiceOption[];
  count: number;
  locale_prefix: string;
  default_voice: string;
}

export interface LanguageOption {
  code: string;
  name: string;
  native_name?: string;
  default_voice?: string;
}

export interface SceneSlot {
  scene_id: number;
  scene_number: number;
  filename: string;
  script_text?: string;
  visual_prompt?: string;
  duration_seconds?: number;
  ready: boolean;
  preview_url?: string | null;
  source?: string | null;
  error?: string | null;
}

export interface WorkspaceResponse {
  job_id: string;
  title?: string;
  idea?: string;
  style?: string;
  language?: string;
  aspect_ratio?: string;
  can_edit: boolean;
  image_provider?: string;
  scene_count: number;
  scenes_ready: number;
  all_scenes_ready: boolean;
  clipboard_text?: string;
  script_url?: string | null;
  audio_url?: string | null;
  audio_ready?: boolean;
  current_voice?: string | null;
  voice_options?: VoiceOption[];
  bgm_url?: string | null;
  bgm_ready?: boolean;
  video_url?: string | null;
  subtitles_url?: string | null;
  prompts_url?: string | null;
  prompts_txt_url?: string | null;
  prompts_csv_url?: string | null;
  scenes: SceneSlot[];
}

export interface JobSummary {
  job_id: string;
  status: JobStatus;
  title?: string | null;
  idea?: string | null;
  scene_count?: number | null;
  updated_at?: string | null;
  can_edit?: boolean;
  thumb_url?: string | null;
  video_url?: string | null;
  progress_percent?: number;
}
