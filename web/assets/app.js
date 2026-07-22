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
  const preview = document.getElementById("preview");
  const dlVideo = document.getElementById("dl-video");
  const dlAudio = document.getElementById("dl-audio");
  const dlScript = document.getElementById("dl-script");
  const newJobBtn = document.getElementById("new-job-btn");

  let pollTimer = null;
  let activeJobId = null;

  function setBusy(busy) {
    submitBtn.disabled = busy;
    submitBtn.querySelector(".cta-label").textContent = busy ? "Generating…" : "Generate video";
  }

  function showPanel(jobId) {
    panel.hidden = false;
    jobIdLabel.textContent = `Job ${jobId}`;
    resultBlock.hidden = true;
    errorLabel.hidden = true;
    errorLabel.textContent = "";
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

    if (state.status === "completed" && state.download_urls) {
      const urls = state.download_urls;
      if (urls.video_url) {
        preview.src = urls.video_url;
        dlVideo.href = urls.video_url;
      }
      if (urls.audio_url) dlAudio.href = urls.audio_url;
      if (urls.script_url) dlScript.href = urls.script_url;
      resultBlock.hidden = false;
    }
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
      hint.textContent = "Rendering in the background. Progress updates live.";
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
    panel.hidden = true;
    resultBlock.hidden = true;
    setBusy(false);
    hint.textContent = "Runs in the background — you can leave this tab open.";
    document.getElementById("idea").focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  window.addEventListener("beforeunload", stopPolling);
})();
