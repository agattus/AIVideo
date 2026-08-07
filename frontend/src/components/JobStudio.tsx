import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  BGM_STYLE_OPTIONS,
  LANGUAGE_DEFAULT_VOICES,
  assembleVideo,
  copyText,
  generateMissingImages,
  generateSceneImage,
  getJobStatus,
  getWorkspace,
  previewVoice,
  updateBgm,
  updateCastVoices,
  updateSceneAmbience,
  updateVoiceover,
  uploadAssetsZip,
  uploadScene,
} from "../api/client";
import type {
  AmbienceTag,
  JobStatusResponse,
  SceneSlot,
  WorkspaceResponse,
} from "../api/types";
import { deriveYoutubeReachAutoDone } from "../lib/youtubeReachProgress";
import { ProgressMeter } from "./ProgressMeter";
import { StudioSection } from "./StudioSection";
import { VoicePicker } from "./VoicePicker";
import { YouTubeReachGuide } from "./YouTubeReachGuide";

type SectionId =
  | "video"
  | "assemble"
  | "youtube"
  | "quiz"
  | "cast"
  | "voice"
  | "bgm"
  | "scenes"
  | "script";

const SCENES_PAGE_SIZE = 12;

type Props = {
  jobId: string;
};

const AMBIENCE_OPTIONS: AmbienceTag[] = [
  "none",
  "rain",
  "wind",
  "forest",
  "city",
  "ocean",
  "fire",
  "night",
  "room",
];

function aspectClass(ratio?: string | null) {
  if (ratio === "9:16") return "ar-9-16";
  if (ratio === "1:1") return "ar-1-1";
  return "ar-16-9";
}

export function JobStudio({ jobId }: Props) {
  const [status, setStatus] = useState<JobStatusResponse | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<string | null>(null);
  const [locale, setLocale] = useState("en");
  const [voice, setVoice] = useState(LANGUAGE_DEFAULT_VOICES.en);
  const [bgmStyle, setBgmStyle] = useState("cinematic");
  const [assembling, setAssembling] = useState(false);
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [castBusy, setCastBusy] = useState(false);
  const [previewingCastId, setPreviewingCastId] = useState<string | null>(null);
  const [castVoiceMap, setCastVoiceMap] = useState<Record<string, string>>({});
  const [castPreviewUrls, setCastPreviewUrls] = useState<Record<string, string>>({});
  const [generating, setGenerating] = useState<"missing" | "all" | number | null>(null);
  const [updatingAmbience, setUpdatingAmbience] = useState<number | null>(null);
  const [openSections, setOpenSections] = useState<Record<SectionId, boolean>>({
    video: true,
    assemble: true,
    youtube: false,
    quiz: false,
    cast: false,
    voice: false,
    bgm: false,
    scenes: false,
    script: false,
  });
  const [sceneFilter, setSceneFilter] = useState<"all" | "ready" | "missing">("all");
  const [expandedSceneId, setExpandedSceneId] = useState<number | null>(null);
  const [scenePage, setScenePage] = useState(0);
  const voiceFileRef = useRef<HTMLInputElement>(null);
  const bgmFileRef = useRef<HTMLInputElement>(null);
  const zipFileRef = useRef<HTMLInputElement>(null);
  const lastKey = useRef("");
  const sectionsPrimed = useRef(false);
  const voiceBusyRef = useRef(false);

  const hasWorkspace = useRef(false);

  const loadWs = useCallback(async (force = false) => {
    try {
      const ws = await getWorkspace(jobId);
      setWorkspace(ws);
      hasWorkspace.current = true;
      if (ws.language) setLocale(ws.language);
      if (ws.current_voice && ws.current_voice !== "custom_upload") {
        setVoice(ws.current_voice);
      }
      if (ws.style) setBgmStyle(ws.style);
      if (force) setError(null);
    } catch (err) {
      if (hasWorkspace.current) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }
  }, [jobId]);

  useEffect(() => {
    lastKey.current = "";
    hasWorkspace.current = false;
    sectionsPrimed.current = false;
    setWorkspace(null);
    setStatus(null);
    setError(null);
    setAction(null);
    setCastBusy(false);
    setPreviewingCastId(null);
    setCastVoiceMap({});
    setCastPreviewUrls({});
    setGenerating(null);
    setUpdatingAmbience(null);
    setExpandedSceneId(null);
    setScenePage(0);
    setSceneFilter("all");

    let cancelled = false;

    const tick = async () => {
      try {
        const state = await getJobStatus(jobId);
        if (cancelled) return;
        setStatus(state);
        if (state.error) setError(state.error);

        const ready =
          state.status === "waiting_for_assets" ||
          state.status === "completed" ||
          state.status === "failed" ||
          Boolean(state.run_dir && state.download_urls);

        if (ready) {
          const key = `${state.status}|${state.progress_percent}|${state.current_stage || ""}`;
          if (key !== lastKey.current) {
            lastKey.current = key;
            await loadWs(true);
          }
        }

        if (state.status === "completed" || state.status === "failed") {
          setAssembling(false);
        }

        const stage = (state.current_stage || "").toLowerCase();
        const voiceWorking =
          state.status === "processing" &&
          (stage.includes("voice") ||
            stage.includes("narration") ||
            stage.includes("recording narration") ||
            stage.includes("stitching narration"));
        if (voiceWorking) {
          voiceBusyRef.current = true;
          setVoiceBusy(true);
          setAction(state.current_stage || "Regenerating voiceover…");
        } else if (
          voiceBusyRef.current &&
          state.status === "waiting_for_assets" &&
          stage.includes("voice updated")
        ) {
          voiceBusyRef.current = false;
          setVoiceBusy(false);
          setAction(state.current_stage || "Voiceover updated.");
          await loadWs(true);
        } else if (
          voiceBusyRef.current &&
          state.status === "waiting_for_assets" &&
          (stage.includes("failed") || Boolean(state.error))
        ) {
          voiceBusyRef.current = false;
          setVoiceBusy(false);
          if (!state.error) setAction(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    };

    tick();
    const timer = window.setInterval(tick, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [jobId, loadWs]);
  const canEdit = Boolean(workspace?.can_edit);
  // Manual provider always 400s on generate; hide the buttons instead of
  // letting the user hit a dead end.
  const canGenerate = canEdit && workspace?.image_provider !== "manual";
  const scenes: SceneSlot[] = workspace?.scenes || [];

  useEffect(() => {
    if (!workspace || sectionsPrimed.current) return;
    sectionsPrimed.current = true;
    const missing = Math.max(0, (workspace.scene_count || 0) - (workspace.scenes_ready || 0));
    setOpenSections({
      video: Boolean(workspace.video_url),
      assemble: canEdit && !workspace.video_url,
      youtube: true,
      quiz: workspace.format === "quizverse",
      cast: workspace.format === "dialogue",
      voice: canEdit && !workspace.video_url,
      bgm: false,
      scenes: missing > 0 || !workspace.video_url,
      script: false,
    });
  }, [workspace, canEdit]);

  useEffect(() => {
    if (workspace?.format !== "dialogue") return;
    setCastVoiceMap(
      Object.fromEntries((workspace.cast || []).map((member) => [member.id, member.voice_id])),
    );
  }, [workspace?.format, workspace?.cast]);

  const filmTitle =
    workspace?.title || status?.title || workspace?.idea || status?.idea || "";

  const youtubeAutoDone = useMemo(
    () => deriveYoutubeReachAutoDone(status, workspace),
    [status, workspace],
  );

  useEffect(() => {
    const previous = document.title;
    document.title = filmTitle ? `${filmTitle} · S-Studio` : "S-Studio";
    return () => {
      document.title = previous;
    };
  }, [filmTitle]);

  function toggleSection(id: SectionId) {
    setOpenSections((prev) => ({ ...prev, [id]: !prev[id] }));
  }

  const filteredScenes = useMemo(() => {
    if (sceneFilter === "ready") return scenes.filter((s) => s.ready);
    if (sceneFilter === "missing") return scenes.filter((s) => !s.ready);
    return scenes;
  }, [scenes, sceneFilter]);

  const scenePageCount = Math.max(1, Math.ceil(filteredScenes.length / SCENES_PAGE_SIZE));
  const safeScenePage = Math.min(scenePage, scenePageCount - 1);
  const pagedScenes = filteredScenes.slice(
    safeScenePage * SCENES_PAGE_SIZE,
    safeScenePage * SCENES_PAGE_SIZE + SCENES_PAGE_SIZE,
  );

  const metaLine = useMemo(() => {
    if (!workspace) return "";
    const title = (workspace.title || "").trim().toLowerCase();
    const idea = (workspace.idea || "").trim();
    const showIdea = idea && idea.toLowerCase() !== title;
    return [
      showIdea ? idea : null,
      workspace.style || null,
      workspace.aspect_ratio || null,
      `${workspace.scenes_ready || 0}/${workspace.scene_count || 0} images`,
    ]
      .filter(Boolean)
      .join(" · ");
  }, [workspace]);

  async function onCopyAll() {
    const ok = await copyText(workspace?.clipboard_text || "");
    setAction(
      ok
        ? "All visual prompts copied — paste them into Flow for alternate images."
        : "Could not copy automatically — download prompts.txt instead.",
    );
  }

  async function onCopyCommunityPostDraft() {
    const ok = await copyText(workspace?.community_post_draft || "");
    setAction(ok ? "Community post draft copied." : "Could not copy community post draft.");
  }

  async function onGenerateMissing() {
    setGenerating("missing");
    setAction("Regenerating missing scene images…");
    setError(null);
    try {
      const detail = await generateMissingImages(jobId, false);
      setAction(detail.message || "Missing scene images regenerated.");
      await loadWs(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(null);
    }
  }

  async function onGenerateAll() {
    setGenerating("all");
    setAction("Regenerating all scene images…");
    setError(null);
    try {
      const detail = await generateMissingImages(jobId, true);
      setAction(detail.message || "All scene images regenerated.");
      await loadWs(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(null);
    }
  }

  async function onGenerateScene(scene: SceneSlot) {
    setGenerating(scene.scene_id);
    setAction(`Regenerating scene ${scene.scene_number}…`);
    setError(null);
    try {
      const detail = await generateSceneImage(jobId, scene.scene_id);
      setAction(detail.message || `Scene ${scene.scene_number} regenerated.`);
      await loadWs(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(null);
    }
  }

  async function onOpenFlow(scene: SceneSlot) {
    const prompt = scene.visual_prompt || "";
    try {
      await navigator.clipboard.writeText(prompt);
      setAction(`Copied prompt for scene ${scene.scene_number} and opened Flow.`);
    } catch {
      setAction("Could not copy automatically — copy the prompt manually in Flow.");
    }
    window.open(
      "https://labs.google/fx/tools/flow",
      "_blank",
      "noopener,noreferrer",
    );
  }

  async function onUploadScene(sceneId: number, file: File) {
    setAction(`Uploading scene ${sceneId + 1}…`);
    try {
      const detail = await uploadScene(jobId, sceneId, file);
      setAction(detail.message || `Saved scene ${sceneId}`);
      await loadWs(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onAmbienceChange(scene: SceneSlot, ambience: AmbienceTag) {
    setUpdatingAmbience(scene.scene_id);
    setAction(`Updating ambience for scene ${scene.scene_number}…`);
    setError(null);
    try {
      const detail = await updateSceneAmbience(jobId, scene.scene_id, ambience);
      setAction(detail.message || `Scene ${scene.scene_number} ambience updated.`);
      await loadWs(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUpdatingAmbience(null);
    }
  }

  async function onZipUpload() {
    const file = zipFileRef.current?.files?.[0];
    if (!file) {
      setAction("Choose a .zip first.");
      return;
    }
    setAction("Placing ZIP images…");
    try {
      const detail = await uploadAssetsZip(jobId, file);
      setAction(detail.message || "ZIP images placed.");
      await loadWs(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onVoiceUpdate() {
    setError(null);
    voiceBusyRef.current = true;
    setVoiceBusy(true);
    setAction(
      `Regenerating voiceover with ${voice}… for a long script this can take several minutes.`,
    );
    try {
      const detail = await updateVoiceover(jobId, { voice });
      setAction(
        detail.message ||
          `Regenerating voiceover with ${voice} in the background…`,
      );
      // Keep voiceBusy true while status polling shows PROCESSING.
      if (detail.status && detail.status !== "processing") {
        voiceBusyRef.current = false;
        setVoiceBusy(false);
        await loadWs(true);
      } else {
        lastKey.current = "";
        const state = await getJobStatus(jobId);
        setStatus(state);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setAction(null);
      voiceBusyRef.current = false;
      setVoiceBusy(false);
    }
  }

  async function onVoiceUpload() {
    const file = voiceFileRef.current?.files?.[0];
    if (!file) {
      setAction("Choose a narration audio file first.");
      return;
    }
    setError(null);
    setVoiceBusy(true);
    setAction("Uploading custom voiceover…");
    try {
      const detail = await updateVoiceover(jobId, { file });
      setAction(detail.message || "Custom voiceover saved.");
      await loadWs(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setAction(null);
    } finally {
      setVoiceBusy(false);
    }
  }

  async function onCastPreview(memberId: string, selectedVoice: string) {
    if (!selectedVoice) return;
    setPreviewingCastId(memberId);
    setError(null);
    setAction(`Generating sample for ${selectedVoice}…`);
    try {
      const detail = await previewVoice(selectedVoice);
      setCastPreviewUrls((prev) => ({ ...prev, [memberId]: detail.preview_url }));
      setAction(detail.message || `Preview ready: ${selectedVoice}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewingCastId(null);
    }
  }

  async function onCastSave(regenerate: boolean) {
    const voiceMap = Object.fromEntries(
      (workspace?.cast || [])
        .map((member) => [member.id, castVoiceMap[member.id]] as const)
        .filter((entry): entry is readonly [string, string] => Boolean(entry[1])),
    );
    if (Object.keys(voiceMap).length !== (workspace?.cast || []).length) {
      setError("Choose a voice for every cast member.");
      return;
    }

    setCastBusy(true);
    setError(null);
    setAction(regenerate ? "Saving cast and regenerating dialogue voiceover…" : "Saving cast voices…");
    try {
      const detail = await updateCastVoices(jobId, voiceMap, regenerate);
      setAction(detail.message || "Cast voices updated.");
      if (regenerate) {
        voiceBusyRef.current = true;
        setVoiceBusy(true);
        lastKey.current = "";
        setStatus(await getJobStatus(jobId));
      } else {
        await loadWs(true);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setAction(null);
    } finally {
      setCastBusy(false);
    }
  }

  async function onBgmRefetch() {
    setAction("Fetching new BGM…");
    try {
      const detail = await updateBgm(jobId, { style: bgmStyle });
      setAction(detail.message || "BGM updated.");
      await loadWs(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onBgmUpload() {
    const file = bgmFileRef.current?.files?.[0];
    if (!file) {
      setAction("Choose an audio file first.");
      return;
    }
    setAction("Uploading BGM…");
    try {
      const detail = await updateBgm(jobId, { file });
      setAction(detail.message || "Custom BGM saved.");
      await loadWs(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onAssemble() {
    setAssembling(true);
    setAction("Assembling cinematic video…");
    try {
      await assembleVideo(jobId);
      lastKey.current = "";
      const state = await getJobStatus(jobId);
      setStatus(state);
    } catch (err) {
      setAssembling(false);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="studio-page">
      <div className="studio-header">
        <div>
          <p className="job-id">Your film</p>
          <h1>{filmTitle || "Untitled film"}</h1>
          {metaLine ? <p className="studio-meta">{metaLine}</p> : null}
        </div>
        <Link className="text-btn" to="/">
          Start another film
        </Link>
      </div>

      <ProgressMeter
        percent={status?.progress_percent ?? 0}
        status={status?.status || "queued"}
        stage={status?.current_stage || "Getting ready…"}
        scenesDone={status?.scenes_done}
        scenesTotal={status?.scenes_total ?? status?.scene_count}
      />

      {error ? <p className="error-banner">{error}</p> : null}
      {action ? <p className="action-banner">{action}</p> : null}

      {!workspace && status?.status !== "failed" ? (
        <p className="empty-note">
          We’re writing the script and recording the voice — the studio opens when that’s done.
        </p>
      ) : null}

      {workspace ? (
        <div className="studio-panels">
          <nav className="studio-jump" aria-label="Studio sections">
            {(
              [
                workspace.video_url ? (["video", "Video"] as const) : null,
                canEdit ? (["assemble", "Assemble"] as const) : null,
                ["youtube", "YouTube"] as const,
                workspace.format === "quizverse" ? (["quiz", "Quiz"] as const) : null,
                workspace.format === "dialogue" ? (["cast", "Cast"] as const) : null,
                ["voice", "Voice"] as const,
                ["bgm", "Music"] as const,
                ["scenes", "Scenes"] as const,
                ["script", "Script"] as const,
              ].filter(Boolean) as Array<readonly [SectionId, string]>
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={`studio-jump-btn${openSections[id] ? " active" : ""}`}
                onClick={() => {
                  setOpenSections((prev) => ({ ...prev, [id]: true }));
                  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
              >
                {label}
              </button>
            ))}
          </nav>

          {workspace.video_url ? (
            <StudioSection
              id="video"
              title="Final video"
              summary="Ready to watch"
              open={openSections.video}
              onToggle={() => toggleSection("video")}
              accent
            >
              <video
                className={`preview-video ${aspectClass(workspace.aspect_ratio)}`}
                controls
                playsInline
                src={workspace.video_url}
              />
              <div className="link-row">
                <a className="link-btn" href={workspace.video_url} download>
                  Download MP4
                </a>
                {workspace.subtitles_url ? (
                  <a className="link-btn" href={workspace.subtitles_url} download>
                    Download SRT
                  </a>
                ) : null}
              </div>
            </StudioSection>
          ) : null}

          {canEdit ? (
            <StudioSection
              id="assemble"
              title="Assemble"
              summary={
                workspace.all_scenes_ready
                  ? "Ready"
                  : `${workspace.scenes_ready}/${workspace.scene_count} images`
              }
              open={openSections.assemble}
              onToggle={() => toggleSection("assemble")}
              accent
            >
              <div className="inline-actions" style={{ marginTop: 0 }}>
                <button
                  type="button"
                  className="cta"
                  disabled={!workspace.all_scenes_ready || assembling}
                  onClick={onAssemble}
                >
                  {assembling ? "Assembling…" : "Assemble final video"}
                </button>
              </div>
              <p className="panel-note">
                {!workspace.all_scenes_ready
                  ? `Need every scene image first (${workspace.scenes_ready}/${workspace.scene_count}).`
                  : "Images are ready — assemble after voice and music sound right."}
              </p>
            </StudioSection>
          ) : null}

          <StudioSection
            id="youtube"
            title="Get it on YouTube’s algorithm"
            summary={`${Object.values(youtubeAutoDone).filter(Boolean).length}/10 pipeline`}
            open={openSections.youtube}
            onToggle={() => toggleSection("youtube")}
            accent
          >
            <YouTubeReachGuide
              filmTitle={filmTitle || workspace.title || "Untitled film"}
              idea={workspace.idea || ""}
              style={workspace.style || ""}
              aspectRatio={workspace.aspect_ratio || "16:9"}
              autoDone={youtubeAutoDone}
              onStatus={setAction}
            />
          </StudioSection>

          {workspace.format === "quizverse" ? (
            <StudioSection
              id="quiz"
              title="Quiz"
              summary={`${workspace.quiz_answer_key?.length || 0} answers`}
              open={openSections.quiz}
              onToggle={() => toggleSection("quiz")}
            >
              {workspace.quiz_answer_key?.length ? (
                <div className="script-list">
                  {workspace.quiz_answer_key.map((item, index) => (
                    <article className="script-scene" key={`${index}-${item.question}`}>
                      <header>
                        <strong>Question {index + 1}</strong>
                        <span>{workspace.quiz_mode || "quiz"}</span>
                      </header>
                      <p>{item.question}</p>
                      {item.choices?.length ? (
                        <p className="panel-note">{item.choices.join(" · ")}</p>
                      ) : null}
                      <p>
                        <strong>Answer:</strong> {item.answer}
                      </p>
                      {item.explain ? <p className="panel-note">{item.explain}</p> : null}
                    </article>
                  ))}
                </div>
              ) : (
                <p className="panel-note">Answer key appears after the quiz script is ready.</p>
              )}
              <div className="inline-actions">
                <button
                  type="button"
                  className="cta secondary"
                  disabled={!workspace.community_post_draft}
                  onClick={onCopyCommunityPostDraft}
                >
                  Copy community post draft
                </button>
              </div>
            </StudioSection>
          ) : null}

          {workspace.format === "dialogue" ? (
            <StudioSection
              id="cast"
              title="Cast"
              summary={`${workspace.cast?.length || 0} characters`}
              open={openSections.cast}
              onToggle={() => toggleSection("cast")}
            >
              {workspace.cast?.length ? (
                <>
                  <div className="script-list">
                    {workspace.cast.map((member) => {
                      const selectedVoice = castVoiceMap[member.id] || member.voice_id;
                      return (
                        <article className="script-scene" key={member.id}>
                          <header>
                            <strong>{member.name}</strong>
                            <span>{member.id}</span>
                          </header>
                          <div className="field-grid" style={{ marginTop: 0 }}>
                            <label className="field">
                              <span>Character voice</span>
                              <select
                                value={selectedVoice}
                                disabled={!canEdit || castBusy}
                                onChange={(event) =>
                                  setCastVoiceMap((prev) => ({
                                    ...prev,
                                    [member.id]: event.target.value,
                                  }))
                                }
                              >
                                {workspace.voice_options?.length ? (
                                  workspace.voice_options.map((option) => (
                                    <option key={option.id} value={option.id}>
                                      {option.label || option.id}
                                    </option>
                                  ))
                                ) : (
                                  <option value={selectedVoice}>{selectedVoice}</option>
                                )}
                              </select>
                            </label>
                            <div>
                              <button
                                type="button"
                                className="cta secondary"
                                disabled={!selectedVoice || previewingCastId !== null}
                                onClick={() => onCastPreview(member.id, selectedVoice)}
                              >
                                {previewingCastId === member.id ? "Previewing…" : "Preview voice"}
                              </button>
                            </div>
                          </div>
                          {castPreviewUrls[member.id] ? (
                            <audio
                              className="audio-player"
                              controls
                              autoPlay
                              src={castPreviewUrls[member.id]}
                            />
                          ) : null}
                        </article>
                      );
                    })}
                  </div>
                  {canEdit ? (
                    <div className="inline-actions">
                      <button
                        type="button"
                        className="cta secondary"
                        disabled={castBusy}
                        onClick={() => onCastSave(false)}
                      >
                        {castBusy ? "Saving…" : "Save voice map"}
                      </button>
                      <button
                        type="button"
                        className="cta"
                        disabled={castBusy || voiceBusy}
                        onClick={() => onCastSave(true)}
                      >
                        {voiceBusy ? "Regenerating…" : "Save & regenerate VO"}
                      </button>
                    </div>
                  ) : null}
                </>
              ) : (
                <p className="panel-note">Cast appears after the dialogue script is ready.</p>
              )}
            </StudioSection>
          ) : null}

          <StudioSection
            id="voice"
            title="Voiceover"
            summary={
              workspace.current_voice === "custom_upload"
                ? "Custom upload"
                : workspace.current_voice || "Not set"
            }
            open={openSections.voice}
            onToggle={() => toggleSection("voice")}
          >
            {!workspace.audio_url ? (
              <p className="panel-note">Voiceover appears after TTS finishes.</p>
            ) : (
              <>
                <audio
                  key={`audio-${workspace.audio_version || workspace.audio_url}`}
                  className="audio-player"
                  controls
                  preload="metadata"
                  src={`${workspace.audio_url}?v=${encodeURIComponent(
                    workspace.audio_version || "1",
                  )}`}
                />
                <div className="link-row">
                  <a
                    className="link-btn"
                    href={`${workspace.audio_url}?v=${encodeURIComponent(
                      workspace.audio_version || "1",
                    )}`}
                    download
                  >
                    Download audio MP3
                  </a>
                </div>
              </>
            )}
            <p className="panel-note">
              {workspace.current_voice === "custom_upload"
                ? "Using custom uploaded narration. Preview a speaker, then Update voiceover."
                : `Current speaker: ${workspace.current_voice || "default"}${
                    workspace.language ? ` · language=${workspace.language}` : ""
                  }`}
            </p>
            {canEdit ? (
              <>
                <VoicePicker
                  locale={locale}
                  voice={voice}
                  preferredVoice={
                    workspace.current_voice !== "custom_upload"
                      ? workspace.current_voice || undefined
                      : LANGUAGE_DEFAULT_VOICES[workspace.language || "en"]
                  }
                  onLocaleChange={setLocale}
                  onVoiceChange={setVoice}
                  onStatus={setAction}
                  compact
                />
                <label className="field" style={{ marginTop: "0.85rem" }}>
                  <span>Or upload your own narration</span>
                  <input ref={voiceFileRef} type="file" accept="audio/*,.mp3,.wav,.m4a" />
                </label>
                <div className="inline-actions">
                  <button
                    type="button"
                    className="cta secondary"
                    onClick={onVoiceUpdate}
                    disabled={voiceBusy}
                  >
                    {voiceBusy ? "Regenerating voice…" : "Update voiceover"}
                  </button>
                  <button
                    type="button"
                    className="cta secondary"
                    onClick={onVoiceUpload}
                    disabled={voiceBusy}
                  >
                    Use uploaded audio
                  </button>
                </div>
                {voiceBusy ? (
                  <p className="panel-note">
                    Stay on this page — Edge TTS is rewriting the full narration.
                  </p>
                ) : null}
              </>
            ) : null}
          </StudioSection>

          <StudioSection
            id="bgm"
            title="Background music"
            summary={workspace.bgm_ready ? "Loaded" : "Missing"}
            open={openSections.bgm}
            onToggle={() => toggleSection("bgm")}
          >
            {workspace.bgm_ready && workspace.bgm_url ? (
              <>
                <p className="panel-note">Current BGM — listen, or replace if you don’t like it.</p>
                <audio
                  className="audio-player"
                  controls
                  preload="none"
                  src={`${workspace.bgm_url}?t=${Date.now()}`}
                />
              </>
            ) : (
              <p className="panel-note">No BGM yet — refetch a style bed or upload your own .mp3.</p>
            )}
            {canEdit ? (
              <>
                <div className="field-grid" style={{ marginTop: "0.75rem" }}>
                  <label className="field">
                    <span>Refetch style</span>
                    <select value={bgmStyle} onChange={(e) => setBgmStyle(e.target.value)}>
                      {BGM_STYLE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Or upload your own track</span>
                    <input ref={bgmFileRef} type="file" accept="audio/*,.mp3,.wav,.m4a" />
                  </label>
                </div>
                <div className="inline-actions">
                  <button type="button" className="cta secondary" onClick={onBgmRefetch}>
                    Get new BGM
                  </button>
                  <button type="button" className="cta secondary" onClick={onBgmUpload}>
                    Use uploaded BGM
                  </button>
                </div>
              </>
            ) : null}
          </StudioSection>

          <StudioSection
            id="scenes"
            title="Scene images"
            summary={`${workspace.scenes_ready}/${workspace.scene_count} ready`}
            open={openSections.scenes}
            onToggle={() => toggleSection("scenes")}
          >
            <p className="panel-note">
              {canGenerate
                ? "Tap a scene to edit prompts, ambience, or regenerate. Long lists are paged."
                : "Tap a scene to upload or replace its image."}
            </p>
            {canEdit ? (
              <div className="toolbar">
                {canGenerate ? (
                  <>
                    <button
                      type="button"
                      className="cta secondary"
                      disabled={generating !== null}
                      onClick={onGenerateMissing}
                    >
                      {generating === "missing" ? "Regenerating…" : "Regenerate missing"}
                    </button>
                    <button
                      type="button"
                      className="cta secondary"
                      disabled={generating !== null}
                      onClick={onGenerateAll}
                    >
                      {generating === "all" ? "Regenerating…" : "Regenerate all"}
                    </button>
                  </>
                ) : null}
                <button type="button" className="cta secondary" onClick={onCopyAll}>
                  Copy all prompts
                </button>
                {workspace.prompts_url ? (
                  <a className="link-btn" href={workspace.prompts_url} download>
                    prompts.json
                  </a>
                ) : null}
              </div>
            ) : null}

            <div className="scene-filter-row">
              {(
                [
                  ["all", `All (${scenes.length})`],
                  ["ready", `Ready (${scenes.filter((s) => s.ready).length})`],
                  ["missing", `Missing (${scenes.filter((s) => !s.ready).length})`],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className={`studio-jump-btn${sceneFilter === id ? " active" : ""}`}
                  onClick={() => {
                    setSceneFilter(id);
                    setScenePage(0);
                  }}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="scene-grid compact">
              {pagedScenes.map((scene) => {
                const expanded = expandedSceneId === scene.scene_id;
                return (
                  <article
                    key={scene.scene_id}
                    className={`scene-card ${scene.ready ? "ready" : "missing"}${
                      expanded ? " expanded" : " collapsed"
                    }`}
                  >
                    <button
                      type="button"
                      className="scene-compact-toggle"
                      onClick={() =>
                        setExpandedSceneId(expanded ? null : scene.scene_id)
                      }
                    >
                      <div className="scene-media">
                        {scene.ready && scene.preview_url ? (
                          <img
                            src={`${scene.preview_url}?t=${Date.now()}`}
                            alt={scene.filename}
                          />
                        ) : (
                          <div className="scene-placeholder">No image</div>
                        )}
                      </div>
                      <div className="scene-compact-meta">
                        <strong>Scene {scene.scene_number}</strong>
                        <span className="scene-flag">
                          {scene.ready ? "ready" : "needs image"}
                        </span>
                        <span className="scene-file">
                          {scene.ambience || "none"}
                          {expanded ? " · hide" : " · edit"}
                        </span>
                      </div>
                    </button>

                    {expanded ? (
                      <div className="scene-body">
                        <p className="scene-narration">
                          <span>Narration</span>
                          {scene.script_text || ""}
                        </p>
                        <p className="panel-note">
                          SFX:{" "}
                          {scene.sfx?.length
                            ? scene.sfx.map((cue) => `${cue.tag}@${cue.at}`).join(", ")
                            : "none"}
                        </p>
                        {canEdit ? (
                          <label className="field">
                            <span>Change ambience</span>
                            <select
                              value={scene.ambience || "none"}
                              disabled={updatingAmbience !== null}
                              onChange={(event) =>
                                onAmbienceChange(scene, event.target.value as AmbienceTag)
                              }
                            >
                              {AMBIENCE_OPTIONS.map((ambience) => (
                                <option key={ambience} value={ambience}>
                                  {ambience}
                                </option>
                              ))}
                            </select>
                          </label>
                        ) : null}
                        <label className="prompt-label">Visual prompt</label>
                        <textarea
                          className="scene-prompt-box"
                          readOnly
                          rows={3}
                          value={scene.visual_prompt || ""}
                        />
                        {scene.error ? <p className="error-banner">{scene.error}</p> : null}
                        <div className="scene-actions">
                          {canGenerate ? (
                            <button
                              type="button"
                              className="cta secondary"
                              disabled={generating !== null}
                              onClick={() => onGenerateScene(scene)}
                            >
                              {generating === scene.scene_id ? "Regenerating…" : "Regenerate"}
                            </button>
                          ) : null}
                          <button
                            type="button"
                            className="cta secondary"
                            onClick={async () => {
                              const ok = await copyText(scene.visual_prompt || "");
                              setAction(
                                ok
                                  ? `Copied prompt for scene ${scene.scene_number}.`
                                  : "Copy failed — select the prompt text manually.",
                              );
                            }}
                          >
                            Copy prompt
                          </button>
                          <button
                            type="button"
                            className="cta secondary"
                            onClick={() => onOpenFlow(scene)}
                          >
                            Open Flow
                          </button>
                          {canEdit ? (
                            <label className="file-pill">
                              {scene.ready ? "Replace image" : "Upload image"}
                              <input
                                type="file"
                                accept="image/*"
                                onChange={async (e) => {
                                  const file = e.target.files?.[0];
                                  if (!file) return;
                                  await onUploadScene(scene.scene_id, file);
                                  e.target.value = "";
                                }}
                              />
                            </label>
                          ) : null}
                        </div>
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>

            {filteredScenes.length > SCENES_PAGE_SIZE ? (
              <div className="scene-pager">
                <button
                  type="button"
                  className="cta secondary"
                  disabled={safeScenePage <= 0}
                  onClick={() => setScenePage((p) => Math.max(0, p - 1))}
                >
                  Previous
                </button>
                <span>
                  Page {safeScenePage + 1} / {scenePageCount}
                </span>
                <button
                  type="button"
                  className="cta secondary"
                  disabled={safeScenePage >= scenePageCount - 1}
                  onClick={() =>
                    setScenePage((p) => Math.min(scenePageCount - 1, p + 1))
                  }
                >
                  Next
                </button>
              </div>
            ) : null}

            {canEdit ? (
              <div style={{ marginTop: "1rem" }}>
                <label className="field">
                  <span>Or upload a ZIP of all scene images at once</span>
                  <input ref={zipFileRef} type="file" accept=".zip,application/zip" />
                </label>
                <div className="inline-actions">
                  <button type="button" className="cta secondary" onClick={onZipUpload}>
                    Place ZIP images
                  </button>
                </div>
              </div>
            ) : null}
          </StudioSection>

          <StudioSection
            id="script"
            title="Script"
            summary={`${scenes.length} scenes`}
            open={openSections.script}
            onToggle={() => toggleSection("script")}
          >
            {scenes.length === 0 ? (
              <p className="panel-note">Script appears after Phase 1 finishes.</p>
            ) : (
              <div className="script-list">
                {scenes.map((s) => (
                  <article className="script-scene" key={s.scene_id}>
                    <header>
                      <strong>Scene {s.scene_number}</strong>
                      <span>{Number(s.duration_seconds || 0).toFixed(1)}s</span>
                    </header>
                    <p>{s.script_text || "(no narration)"}</p>
                  </article>
                ))}
              </div>
            )}
            {workspace.script_url ? (
              <div className="link-row">
                <a className="link-btn" href={workspace.script_url} download>
                  Download script JSON
                </a>
              </div>
            ) : null}
          </StudioSection>
        </div>
      ) : null}
    </div>
  );
}
