(() => {
  const form = document.getElementById("generate-form");
  const submitBtn = document.getElementById("submit-btn");
  const hint = document.getElementById("form-hint");
  const panel = document.getElementById("progress-panel");
  const jobIdLabel = document.getElementById("job-id-label");
  const meter = document.getElementById("meter");
  const meterFill = document.getElementById("meter-fill");
  const progressPct = document.getElementById("progress-pct");
  const statusPill = document.getElementById("status-pill");
  const stageLabel = document.getElementById("stage-label");
  const errorLabel = document.getElementById("error-label");
  const actionStatus = document.getElementById("action-status");
  const jobStudio = document.getElementById("job-studio");
  const sceneChecklist = document.getElementById("scene-checklist");
  const studioTitle = document.getElementById("studio-title");
  const studioMeta = document.getElementById("studio-meta");
  const scenesProgress = document.getElementById("scenes-progress");
  const scriptView = document.getElementById("script-view");
  const scriptEmpty = document.getElementById("script-empty");
  const audioEmpty = document.getElementById("audio-empty");
  const voiceStatus = document.getElementById("voice-status");
  const voicePreview = document.getElementById("voice-preview");
  const assembleBtn = document.getElementById("assemble-btn");
  const assembleHint = document.getElementById("assemble-hint");
  const bgmStatus = document.getElementById("bgm-status");
  const bgmPreview = document.getElementById("bgm-preview");
  const finalVideoBlock = document.getElementById("final-video-block");
  const preview = document.getElementById("preview");
  const dlVideo = document.getElementById("dl-video");
  const dlSubtitles = document.getElementById("dl-subtitles");
  const dlAudio = document.getElementById("dl-audio");
  const dlScript = document.getElementById("dl-script");
  const dlPrompts = document.getElementById("dl-prompts");
  const dlPromptsTxt = document.getElementById("dl-prompts-txt");
  const dlPromptsCsv = document.getElementById("dl-prompts-csv");
  const newJobBtn = document.getElementById("new-job-btn");
  const libraryGrid = document.getElementById("library-grid");
  const libraryEmpty = document.getElementById("library-empty");

  let pollTimer = null;
  let activeJobId = null;
  let clipboardText = "";
  let scenePrompts = new Map();
  let lastStudioKey = "";
  let studioOpen = false;

  function setBusy(busy) {
    submitBtn.disabled = busy;
    submitBtn.querySelector(".cta-label").textContent = busy ? "Generating…" : "Generate video";
  }

  function applyPreviewAspect(ratio) {
    const map = { "16:9": "16 / 9", "9:16": "9 / 16", "1:1": "1 / 1" };
    preview.style.aspectRatio = map[ratio] || "16 / 9";
    if (ratio === "9:16") {
      preview.style.maxWidth = "360px";
      preview.style.margin = "0 auto";
    } else if (ratio === "1:1") {
      preview.style.maxWidth = "480px";
      preview.style.margin = "0 auto";
    } else {
      preview.style.maxWidth = "";
      preview.style.margin = "";
    }
  }

  function setAction(msg) {
    actionStatus.hidden = !msg;
    actionStatus.textContent = msg || "";
  }

  function showPanel(jobId) {
    panel.hidden = false;
    jobIdLabel.textContent = `Job ${jobId}`;
    jobStudio.hidden = true;
    studioOpen = false;
    lastStudioKey = "";
    scenePrompts = new Map();
    errorLabel.hidden = true;
    errorLabel.textContent = "";
    setAction("");
    preview.removeAttribute("src");
    updateProgress({
      status: "queued",
      progress_percent: 0,
      current_stage: "Queued — waiting for worker…",
    });
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function updateProgress(state) {
    const pct = Math.max(0, Math.min(100, Number(state.progress_percent || 0)));
    meterFill.style.width = `${pct}%`;
    meter.setAttribute("aria-valuenow", String(pct));
    progressPct.textContent = `${pct}%`;
    statusPill.textContent = state.status || "queued";
    statusPill.className = `status ${state.status || "queued"}`;
    stageLabel.textContent = state.current_stage || "Working…";

    if (state.error) {
      errorLabel.hidden = false;
      errorLabel.textContent = state.error;
    }

    const readyForStudio =
      state.status === "waiting_for_assets" ||
      state.status === "completed" ||
      state.status === "failed" ||
      (state.run_dir && state.download_urls);

    if (readyForStudio && activeJobId) {
      // Open / refresh studio when status changes, not on every poll tick.
      const key = `${state.status}|${state.progress_percent}|${state.current_stage || ""}`;
      if (!studioOpen || key !== lastStudioKey) {
        lastStudioKey = key;
        loadWorkspace(activeJobId, { force: !studioOpen });
      }
    }
  }

  async function loadWorkspace(jobId, { force = false } = {}) {
    if (!jobId) return;
    try {
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/workspace`);
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `Workspace failed (${res.status})`);
      }
      const ws = await res.json();
      renderStudio(ws, { force });
      studioOpen = true;
    } catch (err) {
      console.error(err);
      // Don't spam errors while Phase 1 is still writing run_dir.
      if (studioOpen) {
        errorLabel.hidden = false;
        errorLabel.textContent = err.message || String(err);
      }
    }
  }

  function setEditMode(canEdit) {
    document.querySelectorAll(".edit-only").forEach((el) => {
      el.hidden = !canEdit;
    });
  }

  function renderStudio(ws, { force = false } = {}) {
    jobStudio.hidden = false;
    clipboardText = ws.clipboard_text || "";
    setEditMode(Boolean(ws.can_edit));

    studioTitle.textContent = ws.title || "Job studio";
    studioMeta.textContent = [
      ws.idea ? `Idea: ${ws.idea}` : null,
      ws.style || null,
      ws.aspect_ratio || null,
      `${ws.scenes_ready || 0}/${ws.scene_count || 0} images`,
    ]
      .filter(Boolean)
      .join(" · ");
    scenesProgress.textContent = `${ws.scenes_ready || 0} / ${ws.scene_count || 0} images ready`;

    // Final video — size the player to the job aspect ratio
    applyPreviewAspect(ws.aspect_ratio || "16:9");
    const aspectSelect = document.getElementById("aspect_ratio");
    if (aspectSelect && ws.aspect_ratio) {
      aspectSelect.value = ws.aspect_ratio;
    }
    if (ws.video_url) {
      finalVideoBlock.hidden = false;
      preview.src = ws.video_url;
      dlVideo.href = ws.video_url;
    } else {
      finalVideoBlock.hidden = true;
      preview.removeAttribute("src");
    }
    if (ws.subtitles_url) {
      dlSubtitles.hidden = false;
      dlSubtitles.href = ws.subtitles_url;
    } else {
      dlSubtitles.hidden = true;
    }

    // Script
    const scenes = ws.scenes || [];
    if (scenes.length) {
      scriptEmpty.hidden = true;
      scriptView.hidden = false;
      scriptView.innerHTML = scenes
        .map(
          (s) => `
          <article class="script-scene">
            <header><strong>Scene ${s.scene_number}</strong>
              <span>${Number(s.duration_seconds || 0).toFixed(1)}s</span>
            </header>
            <p>${escapeHtml(s.script_text || "(no narration)")}</p>
          </article>`
        )
        .join("");
    } else {
      scriptEmpty.hidden = false;
      scriptView.hidden = true;
      scriptView.innerHTML = "";
    }
    if (ws.script_url) {
      dlScript.hidden = false;
      dlScript.href = ws.script_url;
    } else {
      dlScript.hidden = true;
    }

    // Voiceover
    if (ws.audio_url) {
      audioEmpty.hidden = true;
      voicePreview.hidden = false;
      if (force || !voicePreview.getAttribute("src")) {
        voicePreview.src = `${ws.audio_url}?t=${Date.now()}`;
      }
      dlAudio.hidden = false;
      dlAudio.href = ws.audio_url;
    } else {
      audioEmpty.hidden = false;
      voicePreview.hidden = true;
      voicePreview.removeAttribute("src");
      dlAudio.hidden = true;
    }

    const voiceSelect = document.getElementById("voice-select");
    if (voiceSelect && Array.isArray(ws.voice_options) && ws.voice_options.length) {
      const current = ws.current_voice || voiceSelect.value;
      voiceSelect.innerHTML = ws.voice_options
        .map(
          (opt) =>
            `<option value="${escapeAttr(opt.id)}">${escapeHtml(opt.label)}</option>`
        )
        .join("");
      if ([...voiceSelect.options].some((o) => o.value === current)) {
        voiceSelect.value = current;
      }
    } else if (voiceSelect && ws.current_voice) {
      if ([...voiceSelect.options].some((o) => o.value === ws.current_voice)) {
        voiceSelect.value = ws.current_voice;
      }
    }
    if (voiceStatus) {
      voiceStatus.hidden = false;
      voiceStatus.textContent =
        ws.current_voice === "custom_upload"
          ? "Using your uploaded narration — regenerate with a speaker anytime."
          : `Current speaker: ${ws.current_voice || "default"}. Change it below or upload your own.`;
    }

    // BGM
    if (ws.style) {
      const styleSelect = document.getElementById("bgm-style");
      if ([...styleSelect.options].some((o) => o.value === ws.style)) {
        styleSelect.value = ws.style;
      }
    }
    if (ws.bgm_ready && ws.bgm_url) {
      bgmStatus.textContent = "Current BGM — listen, or replace if you don’t like it.";
      bgmPreview.hidden = false;
      if (force || !bgmPreview.getAttribute("src")) {
        bgmPreview.src = `${ws.bgm_url}?t=${Date.now()}`;
      }
    } else {
      bgmStatus.textContent = "No BGM yet — refetch a style bed or upload your own .mp3.";
      bgmPreview.hidden = true;
      bgmPreview.removeAttribute("src");
    }

    // Prompt downloads
    if (ws.prompts_url) {
      dlPrompts.hidden = false;
      dlPrompts.href = ws.prompts_url;
    }
    if (ws.prompts_txt_url) {
      dlPromptsTxt.hidden = false;
      dlPromptsTxt.href = ws.prompts_txt_url;
    }
    if (ws.prompts_csv_url) {
      dlPromptsCsv.hidden = false;
      dlPromptsCsv.href = ws.prompts_csv_url;
    }

    // Assemble
    assembleBtn.disabled = !(ws.can_edit && ws.all_scenes_ready);
    assembleHint.textContent = !ws.can_edit
      ? "This job is no longer editable."
      : ws.all_scenes_ready
        ? "All scene images are in place — assemble when the BGM sounds right."
        : `Upload every scene image first (${ws.scenes_ready}/${ws.scene_count}).`;

    renderSceneCards(scenes, Boolean(ws.can_edit));
  }

  function renderSceneCards(scenes, canEdit) {
    scenePrompts = new Map();
    sceneChecklist.innerHTML = "";

    if (!scenes.length) {
      sceneChecklist.innerHTML = `<p class="hitl-note">No scenes yet — waiting for script generation.</p>`;
      return;
    }

    scenes.forEach((scene) => {
      scenePrompts.set(String(scene.scene_id), scene.visual_prompt || "");

      const card = document.createElement("article");
      card.className = `scene-card ${scene.ready ? "ready" : "missing"}`;
      card.dataset.sceneId = String(scene.scene_id);

      const media = document.createElement("div");
      media.className = "scene-media";
      if (scene.ready && scene.preview_url) {
        const img = document.createElement("img");
        img.className = "scene-thumb";
        img.alt = scene.filename;
        img.src = `${scene.preview_url}?t=${Date.now()}`;
        media.appendChild(img);
      } else {
        const placeholder = document.createElement("div");
        placeholder.className = "scene-placeholder";
        placeholder.textContent = "No image yet";
        media.appendChild(placeholder);
      }

      const body = document.createElement("div");
      body.className = "scene-body";
      body.innerHTML = `
        <header>
          <strong>Scene ${scene.scene_number}</strong>
          <span class="scene-file">${escapeHtml(scene.filename)}</span>
          <span class="scene-flag">${scene.ready ? "image ready" : "needs image"}</span>
        </header>
        <p class="scene-narration"><span>Narration</span>${escapeHtml(scene.script_text || "")}</p>
        <label class="prompt-label">Visual prompt</label>
        <textarea class="scene-prompt-box" readonly rows="4">${escapeHtml(scene.visual_prompt || "")}</textarea>
      `;

      const actions = document.createElement("div");
      actions.className = "scene-actions";

      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "cta secondary copy-one";
      copyBtn.textContent = "Copy visual prompt";
      copyBtn.addEventListener("click", async () => {
        const text = scenePrompts.get(String(scene.scene_id)) || "";
        const ok = await copyText(text);
        setAction(ok ? `Copied prompt for scene ${scene.scene_number}.` : "Copy failed — select the prompt text manually.");
      });
      actions.appendChild(copyBtn);

      if (canEdit) {
        const uploadLabel = document.createElement("label");
        uploadLabel.className = "cta secondary file-pill-btn";
        uploadLabel.textContent = scene.ready ? "Replace image" : "Upload image";
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*";
        input.className = "scene-file-input";
        input.addEventListener("change", async () => {
          if (!input.files?.length || !activeJobId) return;
          await uploadScene(scene.scene_id, input.files[0]);
          input.value = "";
        });
        uploadLabel.appendChild(input);
        actions.appendChild(uploadLabel);
      }

      body.appendChild(actions);
      card.appendChild(media);
      card.appendChild(body);
      sceneChecklist.appendChild(card);
    });
  }

  async function uploadScene(sceneId, file) {
    const body = new FormData();
    body.append("file", file);
    try {
      setAction(`Uploading scene ${Number(sceneId) + 1}…`);
      const res = await fetch(
        `/api/v1/jobs/${encodeURIComponent(activeJobId)}/scenes/${encodeURIComponent(sceneId)}`,
        { method: "POST", body },
      );
      const detail = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detail.detail || `Upload failed (${res.status})`);
      setAction(detail.message || `Saved scene ${sceneId}`);
      await loadWorkspace(activeJobId, { force: true });
    } catch (err) {
      errorLabel.hidden = false;
      errorLabel.textContent = err.message || String(err);
    }
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function pollStatus(jobId) {
    try {
      const res = await fetch(`/api/v1/status/${encodeURIComponent(jobId)}`);
      if (!res.ok) {
        throw new Error(`Status check failed (${res.status})`);
      }
      const state = await res.json();
      updateProgress(state);
      if (state.status === "completed" || state.status === "failed") {
        stopPolling();
        setBusy(false);
        hint.textContent =
          state.status === "completed"
            ? "Film ready — everything is in the studio below."
            : "Generation failed. Adjust the idea and try again.";
        loadLibrary();
      } else if (state.status === "waiting_for_assets") {
        setBusy(false);
        hint.textContent = "Phase 1 done — use the studio below to copy prompts and upload images.";
        loadLibrary();
      }
    } catch (err) {
      console.error(err);
      errorLabel.hidden = false;
      errorLabel.textContent = err.message || String(err);
    }
  }

  function startPolling(jobId) {
    stopPolling();
    activeJobId = jobId;
    pollStatus(jobId);
    pollTimer = setInterval(() => pollStatus(jobId), 2000);
  }

  async function copyText(text) {
    if (!text) return false;
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    }
  }

  document.getElementById("copy-prompts-btn").addEventListener("click", async () => {
    const ok = await copyText(clipboardText);
    setAction(
      ok
        ? "All visual prompts copied — paste into Meta AI / Gemini."
        : "Could not copy automatically — download prompts.txt instead."
    );
  });

  document.getElementById("zip-upload-btn").addEventListener("click", async () => {
    const input = document.getElementById("zip-upload");
    if (!activeJobId || !input.files?.length) {
      setAction("Choose a .zip first.");
      return;
    }
    const body = new FormData();
    body.append("file", input.files[0]);
    try {
      setAction("Placing ZIP images…");
      const res = await fetch(
        `/api/v1/jobs/${encodeURIComponent(activeJobId)}/upload-assets?assemble=false`,
        { method: "POST", body },
      );
      const detail = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detail.detail || `ZIP upload failed (${res.status})`);
      setAction(detail.message || "ZIP images placed.");
      await loadWorkspace(activeJobId, { force: true });
    } catch (err) {
      errorLabel.hidden = false;
      errorLabel.textContent = err.message || String(err);
    }
  });

  document.getElementById("voice-regen-btn").addEventListener("click", async () => {
    if (!activeJobId) return;
    const body = new FormData();
    body.append("voice", document.getElementById("voice-select").value);
    try {
      setAction("Regenerating voiceover with new speaker…");
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(activeJobId)}/voiceover`, {
        method: "POST",
        body,
      });
      const detail = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detail.detail || `Voiceover regenerate failed (${res.status})`);
      setAction(detail.message || "Voiceover regenerated.");
      voicePreview.removeAttribute("src");
      await loadWorkspace(activeJobId, { force: true });
    } catch (err) {
      errorLabel.hidden = false;
      errorLabel.textContent = err.message || String(err);
    }
  });

  document.getElementById("voice-upload-btn").addEventListener("click", async () => {
    const input = document.getElementById("voice-upload");
    if (!activeJobId || !input.files?.length) {
      setAction("Choose a narration audio file first.");
      return;
    }
    const body = new FormData();
    body.append("file", input.files[0]);
    try {
      setAction("Uploading custom voiceover…");
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(activeJobId)}/voiceover`, {
        method: "POST",
        body,
      });
      const detail = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detail.detail || `Voiceover upload failed (${res.status})`);
      setAction(detail.message || "Custom voiceover saved.");
      voicePreview.removeAttribute("src");
      await loadWorkspace(activeJobId, { force: true });
    } catch (err) {
      errorLabel.hidden = false;
      errorLabel.textContent = err.message || String(err);
    }
  });

  document.getElementById("bgm-refetch-btn").addEventListener("click", async () => {
    if (!activeJobId) return;
    const body = new FormData();
    body.append("style", document.getElementById("bgm-style").value);
    try {
      setAction("Fetching new BGM…");
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(activeJobId)}/bgm`, {
        method: "POST",
        body,
      });
      const detail = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detail.detail || `BGM refetch failed (${res.status})`);
      setAction(detail.message || "BGM updated.");
      bgmPreview.removeAttribute("src");
      await loadWorkspace(activeJobId, { force: true });
    } catch (err) {
      errorLabel.hidden = false;
      errorLabel.textContent = err.message || String(err);
    }
  });

  document.getElementById("bgm-upload-btn").addEventListener("click", async () => {
    const input = document.getElementById("bgm-upload");
    if (!activeJobId || !input.files?.length) {
      setAction("Choose an audio file first.");
      return;
    }
    const body = new FormData();
    body.append("file", input.files[0]);
    try {
      setAction("Uploading BGM…");
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(activeJobId)}/bgm`, {
        method: "POST",
        body,
      });
      const detail = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detail.detail || `BGM upload failed (${res.status})`);
      setAction(detail.message || "Custom BGM saved.");
      bgmPreview.removeAttribute("src");
      await loadWorkspace(activeJobId, { force: true });
    } catch (err) {
      errorLabel.hidden = false;
      errorLabel.textContent = err.message || String(err);
    }
  });

  assembleBtn.addEventListener("click", async () => {
    if (!activeJobId || assembleBtn.disabled) return;
    assembleBtn.disabled = true;
    assembleHint.textContent = "Assembling cinematic video…";
    try {
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(activeJobId)}/assemble`, {
        method: "POST",
      });
      const detail = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detail.detail || `Assemble failed (${res.status})`);
      setBusy(true);
      setAction("Assembling final MP4…");
      hint.textContent = "Assembling final MP4…";
      studioOpen = false;
      lastStudioKey = "";
      startPolling(activeJobId);
    } catch (err) {
      errorLabel.hidden = false;
      errorLabel.textContent = err.message || String(err);
      assembleBtn.disabled = false;
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const idea = document.getElementById("idea").value.trim();
    const style = document.getElementById("style").value;
    const aspect_ratio = document.getElementById("aspect_ratio").value;
    const duration = Number(document.getElementById("duration").value);
    const max_scenes = Number(document.getElementById("max_scenes").value);

    if (idea.length < 3) {
      hint.textContent = "Please enter a longer idea (at least 3 characters).";
      return;
    }

    setBusy(true);
    hint.textContent = "Submitting job…";
    stopPolling();

    try {
      const res = await fetch("/api/v1/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idea, style, aspect_ratio, duration, max_scenes }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `Request failed (${res.status})`);
      }
      const body = await res.json();
      showPanel(body.job_id);
      hint.textContent = "Phase 1 running — script + voice + prompts.";
      startPolling(body.job_id);
    } catch (err) {
      console.error(err);
      setBusy(false);
      hint.textContent = err.message || "Could not start generation.";
      errorLabel.hidden = false;
      errorLabel.textContent = hint.textContent;
      panel.hidden = false;
    }
  });

  async function loadLibrary() {
    if (!libraryGrid) return;
    try {
      const res = await fetch("/api/v1/jobs?limit=40");
      if (!res.ok) throw new Error(`Library failed (${res.status})`);
      const data = await res.json();
      const jobs = data.jobs || [];
      libraryEmpty.hidden = jobs.length > 0;
      libraryGrid.innerHTML = "";
      jobs.forEach((job) => {
        const card = document.createElement("article");
        card.className = "library-card";
        const media =
          job.thumb_url || job.video_url
            ? `<img class="library-thumb" src="${escapeAttr(job.thumb_url || job.video_url)}" alt="" />`
            : `<div class="library-thumb placeholder">No preview</div>`;
        const when = job.updated_at
          ? new Date(job.updated_at).toLocaleString()
          : "";
        card.innerHTML = `
          ${media}
          <div class="library-body">
            <h3>${escapeHtml(job.title || job.job_id)}</h3>
            <p class="library-meta">${escapeHtml(job.status)} · ${job.scene_count || "?"} scenes${when ? ` · ${escapeHtml(when)}` : ""}</p>
            <p class="library-meta">${escapeHtml((job.idea || "").slice(0, 120))}</p>
            <div class="library-actions">
              <button type="button" class="cta secondary open-job" data-job-id="${escapeAttr(job.job_id)}">Open</button>
              ${
                job.can_edit
                  ? `<button type="button" class="cta edit-job" data-job-id="${escapeAttr(job.job_id)}">Edit</button>`
                  : ""
              }
            </div>
          </div>
        `;
        libraryGrid.appendChild(card);
      });
    } catch (err) {
      console.error(err);
      if (libraryEmpty) {
        libraryEmpty.hidden = false;
        libraryEmpty.textContent = err.message || "Could not load previous jobs.";
      }
    }
  }

  async function openExistingJob(jobId, { edit = false } = {}) {
    stopPolling();
    activeJobId = jobId;
    studioOpen = false;
    lastStudioKey = "";
    showPanel(jobId);
    setBusy(false);
    try {
      if (edit) {
        const reopen = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/reopen`, {
          method: "POST",
        });
        const detail = await reopen.json().catch(() => ({}));
        if (!reopen.ok) {
          throw new Error(detail.detail || `Reopen failed (${reopen.status})`);
        }
        setAction(detail.message || "Job reopened for editing.");
      }
      const statusRes = await fetch(`/api/v1/status/${encodeURIComponent(jobId)}`);
      if (statusRes.ok) {
        updateProgress(await statusRes.json());
      }
      await loadWorkspace(jobId, { force: true });
      hint.textContent = edit
        ? "Editing previous job — update voiceover, BGM, or images, then assemble."
        : "Opened previous job in the studio.";
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
      loadLibrary();
    } catch (err) {
      errorLabel.hidden = false;
      errorLabel.textContent = err.message || String(err);
    }
  }

  if (libraryGrid) {
    libraryGrid.addEventListener("click", (event) => {
      const openBtn = event.target.closest(".open-job");
      const editBtn = event.target.closest(".edit-job");
      if (openBtn) {
        openExistingJob(openBtn.getAttribute("data-job-id"), { edit: false });
      } else if (editBtn) {
        openExistingJob(editBtn.getAttribute("data-job-id"), { edit: true });
      }
    });
  }

  document.getElementById("refresh-library-btn")?.addEventListener("click", () => {
    loadLibrary();
  });

  newJobBtn.addEventListener("click", () => {
    stopPolling();
    activeJobId = null;
    studioOpen = false;
    lastStudioKey = "";
    panel.hidden = true;
    jobStudio.hidden = true;
    setBusy(false);
    setAction("");
    hint.textContent = "Runs in the background — you can leave this tab open.";
    document.getElementById("idea").focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
    loadLibrary();
  });

  window.addEventListener("beforeunload", stopPolling);
  loadLibrary();
})();
