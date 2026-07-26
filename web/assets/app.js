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
  const resultBlock = document.getElementById("result-block");
  const hitlPanel = document.getElementById("hitl-panel");
  const sceneChecklist = document.getElementById("scene-checklist");
  const hitlLede = document.getElementById("hitl-lede");
  const copyStatus = document.getElementById("copy-status");
  const assembleBtn = document.getElementById("assemble-btn");
  const assembleHint = document.getElementById("assemble-hint");
  const bgmStatus = document.getElementById("bgm-status");
  const bgmPreview = document.getElementById("bgm-preview");
  const preview = document.getElementById("preview");
  const dlVideo = document.getElementById("dl-video");
  const dlAudio = document.getElementById("dl-audio");
  const dlScript = document.getElementById("dl-script");
  const dlPrompts = document.getElementById("dl-prompts");
  const dlPromptsTxt = document.getElementById("dl-prompts-txt");
  const dlPromptsCsv = document.getElementById("dl-prompts-csv");
  const newJobBtn = document.getElementById("new-job-btn");

  let pollTimer = null;
  let activeJobId = null;
  let clipboardText = "";
  let workspaceLoadedFor = null;

  function setBusy(busy) {
    submitBtn.disabled = busy;
    submitBtn.querySelector(".cta-label").textContent = busy ? "Generating…" : "Generate video";
  }

  function showPanel(jobId) {
    panel.hidden = false;
    jobIdLabel.textContent = `Job ${jobId}`;
    resultBlock.hidden = true;
    hitlPanel.hidden = true;
    errorLabel.hidden = true;
    errorLabel.textContent = "";
    preview.removeAttribute("src");
    workspaceLoadedFor = null;
    updateProgress({
      status: "queued",
      progress_percent: 0,
      current_stage: "Queued — waiting for worker…",
    });
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function showCompleted(state) {
    hitlPanel.hidden = true;
    const urls = state.download_urls || {};
    if (urls.video_url) {
      preview.src = urls.video_url;
      preview.hidden = false;
      dlVideo.href = urls.video_url;
      dlVideo.hidden = false;
    } else {
      preview.hidden = true;
      dlVideo.hidden = true;
    }
    if (urls.audio_url) dlAudio.href = urls.audio_url;
    if (urls.script_url) dlScript.href = urls.script_url;
    let assetsLink = document.getElementById("dl-assets");
    if (urls.assets_url) {
      if (!assetsLink) {
        assetsLink = document.createElement("a");
        assetsLink.id = "dl-assets";
        assetsLink.className = "link-btn ghost";
        assetsLink.textContent = "Scene images";
        dlScript.parentElement.appendChild(assetsLink);
      }
      assetsLink.href = urls.assets_url;
      assetsLink.hidden = false;
    } else if (assetsLink) {
      assetsLink.hidden = true;
    }
    resultBlock.hidden = false;
    const heading = resultBlock.querySelector("h3");
    if (heading) {
      heading.textContent = urls.video_url
        ? "Ready to watch"
        : "Assets ready for manual assembly";
    }
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

    if (state.status === "waiting_for_assets") {
      loadWorkspace(activeJobId);
    } else if (state.status === "completed" && state.download_urls) {
      showCompleted(state);
    } else if (state.status === "processing") {
      hitlPanel.hidden = true;
    }
  }

  async function loadWorkspace(jobId) {
    if (!jobId) return;
    try {
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/workspace`);
      if (!res.ok) {
        throw new Error(`Workspace failed (${res.status})`);
      }
      const ws = await res.json();
      renderWorkspace(ws);
      workspaceLoadedFor = jobId;
    } catch (err) {
      console.error(err);
      errorLabel.hidden = false;
      errorLabel.textContent = err.message || String(err);
    }
  }

  function renderWorkspace(ws) {
    hitlPanel.hidden = false;
    clipboardText = ws.clipboard_text || "";
    hitlLede.textContent = `${ws.title || "Untitled"} · ${ws.scenes_ready}/${ws.scene_count} images · ${ws.aspect_ratio || "16:9"}`;

    if (ws.prompts_url) {
      dlPrompts.href = ws.prompts_url;
      dlPrompts.hidden = false;
    }
    if (ws.prompts_txt_url) {
      dlPromptsTxt.href = ws.prompts_txt_url;
      dlPromptsTxt.hidden = false;
    }
    if (ws.prompts_csv_url) {
      dlPromptsCsv.href = ws.prompts_csv_url;
      dlPromptsCsv.hidden = false;
    }

    if (ws.style) {
      const styleSelect = document.getElementById("bgm-style");
      if ([...styleSelect.options].some((o) => o.value === ws.style)) {
        styleSelect.value = ws.style;
      }
    }

    if (ws.bgm_ready && ws.bgm_url) {
      bgmStatus.textContent = "Current BGM ready — listen below, or replace it.";
      bgmPreview.hidden = false;
      bgmPreview.src = `${ws.bgm_url}?t=${Date.now()}`;
    } else {
      bgmStatus.textContent = "No BGM yet — refetch a style bed or upload your own .mp3.";
      bgmPreview.hidden = true;
      bgmPreview.removeAttribute("src");
    }

    assembleBtn.disabled = !ws.all_scenes_ready;
    assembleHint.textContent = ws.all_scenes_ready
      ? "All scene images are in place — assemble whenever the BGM sounds right."
      : `Upload every scene image first (${ws.scenes_ready}/${ws.scene_count}).`;

    sceneChecklist.innerHTML = "";
    (ws.scenes || []).forEach((scene) => {
      const card = document.createElement("article");
      card.className = `scene-card ${scene.ready ? "ready" : "missing"}`;
      card.innerHTML = `
        <header>
          <strong>Scene ${scene.scene_number}</strong>
          <span class="scene-file">${scene.filename}</span>
          <span class="scene-flag">${scene.ready ? "ready" : "needed"}</span>
        </header>
        <p class="scene-prompt">${escapeHtml(scene.visual_prompt || "")}</p>
        <div class="scene-actions">
          <button type="button" class="text-btn copy-one" data-prompt="${escapeAttr(scene.visual_prompt || "")}">Copy prompt</button>
          <label class="file-pill">
            Upload image
            <input type="file" accept="image/*" data-scene-id="${scene.scene_id}" class="scene-file-input" />
          </label>
        </div>
      `;
      if (scene.preview_url && scene.ready) {
        const img = document.createElement("img");
        img.className = "scene-thumb";
        img.alt = scene.filename;
        img.src = `${scene.preview_url}?t=${Date.now()}`;
        card.appendChild(img);
      }
      sceneChecklist.appendChild(card);
    });
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(text) {
    return escapeHtml(text).replace(/'/g, "&#39;");
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
            ? "Film ready — preview and download below."
            : "Generation failed. Adjust the idea and try again.";
      } else if (state.status === "waiting_for_assets") {
        setBusy(false);
        hint.textContent = "Phase 1 done — copy prompts, upload images, tweak BGM, then assemble.";
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
    copyStatus.hidden = false;
    copyStatus.textContent = ok
      ? "All prompts copied — paste into Meta AI / Gemini."
      : "Could not copy automatically — download prompts.txt instead.";
  });

  sceneChecklist.addEventListener("click", async (event) => {
    const btn = event.target.closest(".copy-one");
    if (!btn) return;
    const ok = await copyText(btn.getAttribute("data-prompt") || "");
    copyStatus.hidden = false;
    copyStatus.textContent = ok ? "Scene prompt copied." : "Copy failed — select the prompt text manually.";
  });

  sceneChecklist.addEventListener("change", async (event) => {
    const input = event.target;
    if (!input.classList.contains("scene-file-input") || !input.files?.length || !activeJobId) {
      return;
    }
    const sceneId = input.getAttribute("data-scene-id");
    const body = new FormData();
    body.append("file", input.files[0]);
    try {
      const res = await fetch(
        `/api/v1/jobs/${encodeURIComponent(activeJobId)}/scenes/${encodeURIComponent(sceneId)}`,
        { method: "POST", body },
      );
      const detail = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detail.detail || `Upload failed (${res.status})`);
      copyStatus.hidden = false;
      copyStatus.textContent = detail.message || `Saved scene ${sceneId}`;
      await loadWorkspace(activeJobId);
    } catch (err) {
      errorLabel.hidden = false;
      errorLabel.textContent = err.message || String(err);
    } finally {
      input.value = "";
    }
  });

  document.getElementById("zip-upload-btn").addEventListener("click", async () => {
    const input = document.getElementById("zip-upload");
    if (!activeJobId || !input.files?.length) {
      copyStatus.hidden = false;
      copyStatus.textContent = "Choose a .zip first.";
      return;
    }
    const body = new FormData();
    body.append("file", input.files[0]);
    try {
      const res = await fetch(
        `/api/v1/jobs/${encodeURIComponent(activeJobId)}/upload-assets?assemble=false`,
        { method: "POST", body },
      );
      const detail = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detail.detail || `ZIP upload failed (${res.status})`);
      copyStatus.hidden = false;
      copyStatus.textContent = detail.message || "ZIP images placed.";
      await loadWorkspace(activeJobId);
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
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(activeJobId)}/bgm`, {
        method: "POST",
        body,
      });
      const detail = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detail.detail || `BGM refetch failed (${res.status})`);
      copyStatus.hidden = false;
      copyStatus.textContent = detail.message || "BGM updated.";
      await loadWorkspace(activeJobId);
    } catch (err) {
      errorLabel.hidden = false;
      errorLabel.textContent = err.message || String(err);
    }
  });

  document.getElementById("bgm-upload-btn").addEventListener("click", async () => {
    const input = document.getElementById("bgm-upload");
    if (!activeJobId || !input.files?.length) {
      copyStatus.hidden = false;
      copyStatus.textContent = "Choose an audio file first.";
      return;
    }
    const body = new FormData();
    body.append("file", input.files[0]);
    try {
      const res = await fetch(`/api/v1/jobs/${encodeURIComponent(activeJobId)}/bgm`, {
        method: "POST",
        body,
      });
      const detail = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(detail.detail || `BGM upload failed (${res.status})`);
      copyStatus.hidden = false;
      copyStatus.textContent = detail.message || "Custom BGM saved.";
      await loadWorkspace(activeJobId);
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
      hitlPanel.hidden = true;
      setBusy(true);
      hint.textContent = "Assembling final MP4…";
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
        body: JSON.stringify({ idea, style, duration, max_scenes }),
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

  newJobBtn.addEventListener("click", () => {
    stopPolling();
    activeJobId = null;
    workspaceLoadedFor = null;
    panel.hidden = true;
    resultBlock.hidden = true;
    hitlPanel.hidden = true;
    setBusy(false);
    hint.textContent = "Runs in the background — you can leave this tab open.";
    document.getElementById("idea").focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  window.addEventListener("beforeunload", stopPolling);
})();
