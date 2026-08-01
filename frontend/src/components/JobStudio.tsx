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
  updateBgm,
  updateVoiceover,
  uploadAssetsZip,
  uploadScene,
} from "../api/client";
import type { JobStatusResponse, SceneSlot, WorkspaceResponse } from "../api/types";
import { ProgressMeter } from "./ProgressMeter";
import { VoicePicker } from "./VoicePicker";

type Props = {
  jobId: string;
};

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
  const [generating, setGenerating] = useState<"missing" | number | null>(null);
  const voiceFileRef = useRef<HTMLInputElement>(null);
  const bgmFileRef = useRef<HTMLInputElement>(null);
  const zipFileRef = useRef<HTMLInputElement>(null);
  const lastKey = useRef("");

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
    setWorkspace(null);
    setStatus(null);
    setError(null);
    setAction(null);
    setGenerating(null);

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
  const scenes: SceneSlot[] = workspace?.scenes || [];

  const metaLine = useMemo(() => {
    if (!workspace) return "";
    return [
      workspace.idea ? `Idea: ${workspace.idea}` : null,
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

  async function onGenerateMissing() {
    setGenerating("missing");
    setAction("Regenerating missing scene images…");
    setError(null);
    try {
      const detail = await generateMissingImages(jobId);
      setAction(detail.message || "Missing scene images regenerated.");
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
    setAction("Updating voiceover with selected edge-tts speaker…");
    try {
      const detail = await updateVoiceover(jobId, { voice });
      setAction(detail.message || "Voiceover updated.");
      await loadWs(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onVoiceUpload() {
    const file = voiceFileRef.current?.files?.[0];
    if (!file) {
      setAction("Choose a narration audio file first.");
      return;
    }
    setAction("Uploading custom voiceover…");
    try {
      const detail = await updateVoiceover(jobId, { file });
      setAction(detail.message || "Custom voiceover saved.");
      await loadWs(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
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
          <p className="job-id">Job {jobId}</p>
          <h1>{workspace?.title || "Job studio"}</h1>
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
          {workspace.video_url ? (
            <section className="panel">
              <h2>Final video</h2>
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
            </section>
          ) : null}

          <section className="panel">
            <h2>Script</h2>
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
          </section>

          <section className="panel">
            <h2>Voiceover</h2>
            {!workspace.audio_url ? (
              <p className="panel-note">Voiceover appears after TTS finishes.</p>
            ) : (
              <>
                <audio
                  className="audio-player"
                  controls
                  preload="metadata"
                  src={`${workspace.audio_url}?t=${Date.now()}`}
                />
                <div className="link-row">
                  <a className="link-btn" href={workspace.audio_url} download>
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
                  <button type="button" className="cta secondary" onClick={onVoiceUpdate}>
                    Update voiceover
                  </button>
                  <button type="button" className="cta secondary" onClick={onVoiceUpload}>
                    Use uploaded audio
                  </button>
                </div>
              </>
            ) : null}
          </section>

          <section className="panel">
            <h2>Background music</h2>
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
          </section>

          <section className="panel">
            <h2>Scene assets</h2>
            <p className="panel-note">
              {workspace.scenes_ready} / {workspace.scene_count} images ready — Gemini generates
              images automatically. Use Flow when you want a different look, then upload the
              replacement here.
            </p>
            {canEdit ? (
              <div className="toolbar">
                <button
                  type="button"
                  className="cta secondary"
                  disabled={generating !== null}
                  onClick={onGenerateMissing}
                >
                  {generating === "missing" ? "Regenerating…" : "Regenerate missing"}
                </button>
                <button type="button" className="cta secondary" onClick={onCopyAll}>
                  Copy all visual prompts
                </button>
                {workspace.prompts_url ? (
                  <a className="link-btn" href={workspace.prompts_url} download>
                    prompts.json
                  </a>
                ) : null}
                {workspace.prompts_txt_url ? (
                  <a className="link-btn" href={workspace.prompts_txt_url} download>
                    prompts.txt
                  </a>
                ) : null}
                {workspace.prompts_csv_url ? (
                  <a className="link-btn" href={workspace.prompts_csv_url} download>
                    prompts.csv
                  </a>
                ) : null}
              </div>
            ) : null}

            <div className="scene-grid">
              {scenes.map((scene) => (
                <article
                  key={scene.scene_id}
                  className={`scene-card ${scene.ready ? "ready" : "missing"}`}
                >
                  <div className="scene-media">
                    {scene.ready && scene.preview_url ? (
                      <img
                        src={`${scene.preview_url}?t=${Date.now()}`}
                        alt={scene.filename}
                      />
                    ) : (
                      <div className="scene-placeholder">No image yet</div>
                    )}
                  </div>
                  <div className="scene-body">
                    <header>
                      <strong>Scene {scene.scene_number}</strong>
                      <span className="scene-file">{scene.filename}</span>
                      <span className="scene-flag">
                        {scene.ready ? "image ready" : "needs image"}
                      </span>
                    </header>
                    <p className="scene-narration">
                      <span>Narration</span>
                      {scene.script_text || ""}
                    </p>
                    <label className="prompt-label">Visual prompt</label>
                    <textarea
                      className="scene-prompt-box"
                      readOnly
                      rows={4}
                      value={scene.visual_prompt || ""}
                    />
                    {scene.error ? <p className="error-banner">{scene.error}</p> : null}
                    <div className="scene-actions">
                      {canEdit ? (
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
                </article>
              ))}
            </div>

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
          </section>

          {canEdit ? (
            <section className="panel">
              <h2>Assemble</h2>
              <div className="inline-actions">
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
                  ? `Upload every scene image first (${workspace.scenes_ready}/${workspace.scene_count}).`
                  : "All scene images are in place — assemble when the BGM sounds right."}
              </p>
            </section>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
