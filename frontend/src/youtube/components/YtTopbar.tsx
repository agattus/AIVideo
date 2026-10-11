import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { IconBell, IconCreate, IconMenu, IconMic, IconSearch } from "./Icons";

type Props = {
  onMenuClick: () => void;
};

export function YtTopbar({ onMenuClick }: Props) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const q = query.trim();
    navigate(q ? `/results?q=${encodeURIComponent(q)}` : "/");
  }

  return (
    <header className="yt-topbar">
      <div className="yt-topbar-left">
        <button
          type="button"
          className="yt-icon-btn"
          aria-label="Menu"
          onClick={onMenuClick}
        >
          <IconMenu />
        </button>
        <Link className="yt-logo" to="/" aria-label="S-Studio home">
          <span className="yt-logo-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="28" height="28">
              <rect width="32" height="32" rx="9" fill="#c7f000" />
              <path
                d="M13 9.5v13l11-6.5-11-6.5z"
                fill="#102000"
              />
            </svg>
          </span>
          <span className="yt-logo-text">
            S-<span className="yt-logo-accent">Studio</span>
          </span>
        </Link>
      </div>

      <form className="yt-search" onSubmit={onSubmit} role="search">
        <div className="yt-search-field">
          <input
            type="search"
            name="q"
            placeholder="Search films"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search films"
          />
          <button type="submit" className="yt-search-submit" aria-label="Search">
            <IconSearch size={22} />
          </button>
        </div>
        <button type="button" className="yt-icon-btn yt-mic" aria-label="Voice search">
          <IconMic />
        </button>
      </form>

      <div className="yt-topbar-right">
        <Link className="yt-icon-btn" to="/create" aria-label="Create">
          <IconCreate />
        </Link>
        <button type="button" className="yt-icon-btn" aria-label="Notifications">
          <IconBell />
          <span className="yt-notif-dot" />
        </button>
        <Link className="yt-avatar-btn" to="/you" aria-label="Your account">
          S
        </Link>
      </div>
    </header>
  );
}
