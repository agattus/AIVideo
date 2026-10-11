import { useState, type FormEvent } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { IconCreate, IconSearch } from "./Icons";

export function YtTopbar() {
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
        <Link className="yt-logo" to="/" aria-label="S-Studio home">
          <span className="yt-logo-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="34" height="34">
              <rect width="32" height="32" rx="9" fill="#c7f000" />
              <path d="M13 9.5v13l11-6.5-11-6.5z" fill="#102000" />
            </svg>
          </span>
          <span className="yt-logo-accent">
            S-<span>Studio</span>
          </span>
        </Link>
      </div>

      <nav className="yt-top-nav" aria-label="Primary">
        <NavLink to="/" end>
          Discover
        </NavLink>
        <NavLink to="/clips">Clips</NavLink>
        <NavLink to="/following">Following</NavLink>
        <NavLink to="/upload">Upload</NavLink>
      </nav>

      <form className="yt-search" onSubmit={onSubmit} role="search">
        <div className="yt-search-field">
          <input
            type="search"
            name="q"
            placeholder="Search creators & films"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search"
          />
          <button type="submit" className="yt-search-submit" aria-label="Search">
            <IconSearch size={20} />
          </button>
        </div>
      </form>

      <div className="yt-topbar-right">
        <Link className="yt-upload-cta" to="/upload">
          <IconCreate size={18} />
          <span className="label">Upload</span>
        </Link>
        <Link className="yt-avatar-btn" to="/you" aria-label="Your profile">
          S
        </Link>
      </div>
    </header>
  );
}
