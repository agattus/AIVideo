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
export type VideoFormat = "narrative" | "quizverse" | "dialogue";
export type QuizMode = "comment" | "reveal";
export type ScriptSource = "generated" | "provided";

export interface GeneratePayload {
  idea: string;
  style: VideoStyle;
  aspect_ratio: AspectRatio;
  duration: number;
  language: string;
  voice: string;
  format?: VideoFormat;
  quiz_mode?: QuizMode;
  question_count?: number;
  script_source?: ScriptSource;
  user_script_text?: string;
  user_script_json?: Record<string, unknown>;
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
  scenes_done?: number | null;
  scenes_total?: number | null;
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
  provider?: string;
}

export interface YoutubeChapter {
  start_seconds: number;
  label: string;
}

export interface YoutubePack {
  mode: "shorts" | "longform" | string;
  language?: string;
  primary_title: string;
  alt_titles?: string[];
  description: string;
  tags?: string[];
  hashtags?: string[];
  pinned_comment?: string;
  chapters?: YoutubeChapter[];
  source?: "llm" | "fallback" | string;
  generated_at?: string;
}

export interface DialogueCastMember {
  id: string;
  name: string;
  voice_id: string;
}

export interface CastVoicesUpdateAccepted {
  job_id: string;
  status: JobStatus;
  cast: DialogueCastMember[];
  regenerate: boolean;
  message?: string;
}

export interface LanguageOption {
  code: string;
  name: string;
  native_name?: string;
  default_voice?: string;
}

export type AmbienceTag =
  | "none"
  | "rain"
  | "wind"
  | "forest"
  | "city"
  | "ocean"
  | "fire"
  | "night"
  | "room";

export interface SfxCue {
  tag: string;
  at: number;
}

export interface SceneSlot {
  scene_id: number;
  scene_number: number;
  filename: string;
  script_text?: string;
  visual_prompt?: string;
  duration_seconds?: number;
  ambience?: AmbienceTag;
  sfx?: SfxCue[];
  ready: boolean;
  preview_url?: string | null;
  source?: string | null;
  error?: string | null;
}

export type ReviewStatus = "pass" | "needs_approval" | "overridden" | "pending";
export type QualityStage = "script" | "timing" | "images";

export interface StageReviewBase {
  status: ReviewStatus;
  issues?: string[];
}

export interface ScriptStageReview extends StageReviewBase {
  scores?: Record<string, number>;
  retries?: number;
}

export interface TimingStageReview extends StageReviewBase {}

export interface ImageStageReview {
  status: ReviewStatus;
  scenes?: Record<string, { score?: number; issue?: string }>;
  retries?: Record<string, number>;
}

export interface QualityReview {
  script_review: ScriptStageReview;
  timing_review: TimingStageReview;
  image_review: ImageStageReview;
  approvals?: Record<string, boolean>;
}

export interface QualityActionResponse {
  job_id: string;
  assemble_allowed: boolean;
  quality_review: QualityReview;
  message?: string;
}

export interface QualityApproveResponse extends QualityActionResponse {
  stage: QualityStage;
}

export interface QualityRegenImagesResponse extends QualityActionResponse {
  regenerated_scenes?: number[];
}

export interface WorkspaceResponse {
  job_id: string;
  title?: string;
  idea?: string;
  script_source?: ScriptSource;
  format?: VideoFormat;
  quiz_mode?: QuizMode | null;
  quiz_answer_key?: Array<{
    question: string;
    choices?: string[];
    answer: string;
    explain?: string;
  }>;
  community_post_draft?: string;
  cast?: DialogueCastMember[];
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
  audio_version?: string | null;
  audio_ready?: boolean;
  current_voice?: string | null;
  voice_options?: VoiceOption[];
  tts_provider?: string | null;
  youtube_pack?: YoutubePack | null;
  bgm_url?: string | null;
  bgm_ready?: boolean;
  video_url?: string | null;
  subtitles_url?: string | null;
  prompts_url?: string | null;
  prompts_txt_url?: string | null;
  prompts_csv_url?: string | null;
  scenes: SceneSlot[];
  quality_review?: QualityReview;
  assemble_allowed?: boolean;
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
