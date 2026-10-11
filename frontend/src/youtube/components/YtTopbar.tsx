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
        <Link className="yt-logo" to="/" aria-label="YouTube replica home">
          <span className="yt-logo-mark" aria-hidden="true">
            <svg viewBox="0 0 28 20" width="28" height="20">
              <rect width="28" height="20" rx="5" fill="#FF0033" />
              <path d="M11 5.5v9l8-4.5-8-4.5z" fill="#fff" />
            </svg>
          </span>
          <span className="yt-logo-text">
            YouTube<span className="yt-logo-badge">CLONE</span>
          </span>
        </Link>
      </div>

      <form className="yt-search" onSubmit={onSubmit} role="search">
        <div className="yt-search-field">
          <input
            type="search"
            name="q"
            placeholder="Search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search"
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
