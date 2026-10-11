import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useYtCatalog } from "../CatalogContext";
import type { YtVideo } from "../types";

export function UploadPage() {
  const { addUpload } = useYtCatalog();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [title, setTitle] = useState("");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [isClip, setIsClip] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function acceptFile(file: File | undefined) {
    if (!file) return;
    if (!file.type.startsWith("video/")) {
      setError("Choose a video file (mp4, mov, webm…).");
      return;
    }
    setError(null);
    setFileName(file.name);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    if (!title.trim()) {
      setTitle(file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "));
    }
    // Heuristic: short files often intended as clips; user can toggle.
    if (file.size < 12_000_000) setIsClip(true);
  }

  function publish() {
    if (!previewUrl) {
      setError("Add a video first.");
      return;
    }
    const id = `up-${Date.now()}`;
    const video: YtVideo = {
      id,
      title: title.trim() || "Untitled upload",
      channel: "You",
      channelHandle: "@you",
      channelAvatar: "https://picsum.photos/seed/you-uploader/88/88",
      views: "0 views",
      uploadedAt: "Just now",
      duration: isClip ? "Clip" : "Film",
      thumbnail: previewUrl,
      videoUrl: previewUrl,
      description: "Uploaded on S-Studio. Share it — let it catch fire.",
      category: isClip ? "Clips" : "Your films",
      likes: "0",
      subscribers: "You",
      isShort: isClip,
      source: "upload",
      heat: "Just dropped",
    };
    addUpload(video);
    navigate(isClip ? `/clips?v=${encodeURIComponent(id)}` : `/watch/${id}`);
  }

  return (
    <div className="ss-upload">
      <h1>Upload & go viral</h1>
      <p>
        Anyone can post a film or a Clip. Drop your file, name it, publish to the
        discovery feed — no gatekeepers.
      </p>

      <div
        className={`ss-drop${drag ? " drag" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          acceptFile(e.dataTransfer.files?.[0]);
        }}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept="video/*"
          aria-label="Choose video file"
          onChange={(e) => acceptFile(e.target.files?.[0])}
        />
        <div>
          <h2>{fileName ? fileName : "Drop your video here"}</h2>
          <p>or click to browse — mp4, mov, webm</p>
        </div>
      </div>

      {previewUrl ? (
        <div className="ss-upload-preview">
          <video src={previewUrl} controls playsInline />
        </div>
      ) : null}

      <label style={{ display: "block", marginTop: 20, fontWeight: 700 }}>
        Title
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Give it a hook"
          style={{
            display: "block",
            width: "100%",
            marginTop: 8,
            minHeight: 48,
            padding: "0 14px",
            borderRadius: 12,
            border: "1px solid rgba(11,15,20,0.12)",
            background: "rgba(255,255,255,0.72)",
          }}
        />
      </label>

      <label
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 10,
          marginTop: 16,
          fontWeight: 600,
          cursor: "pointer",
        }}
      >
        <input
          type="checkbox"
          checked={isClip}
          onChange={(e) => setIsClip(e.target.checked)}
        />
        Publish as a Clip (vertical feed)
      </label>

      {error ? <p className="yt-banner warn">{error}</p> : null}

      <div className="ss-upload-actions">
        <button type="button" className="ss-btn primary" onClick={publish}>
          Publish to feed
        </button>
        <Link className="ss-btn secondary" to="/create">
          Or create with AI
        </Link>
      </div>
    </div>
  );
}
