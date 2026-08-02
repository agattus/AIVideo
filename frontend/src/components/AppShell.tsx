import { useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { Atmosphere } from "./Atmosphere";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [scrolled, setScrolled] = useState(false);
  const location = useLocation();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);

  return (
    <div className="app-shell">
      <Atmosphere />
      <header className={`topbar${scrolled ? " scrolled" : ""}`}>
        <Link className="brand" to="/">
          S-<span>Studio</span>
        </Link>
        <nav className="top-nav" aria-label="Primary">
          <NavLink to="/" end>
            Compose
          </NavLink>
          <Link to="/#library">Library</Link>
          <NavLink to="/studio">Studio</NavLink>
        </nav>
        <div className="top-links-ext">
          <a href="/docs" target="_blank" rel="noopener noreferrer">
            API
          </a>
          <a href="/healthz" target="_blank" rel="noopener noreferrer">
            Status
          </a>
        </div>
      </header>

      <main className="page">{children}</main>

      <footer className="foot">
        <span>S-Studio</span>
        <span>Script → voice → images → cut</span>
      </footer>

      <nav className="bottom-nav" aria-label="Mobile">
        <NavLink to="/" end>
          <span className="nav-icon" aria-hidden="true">
            ✎
          </span>
          Compose
        </NavLink>
        <NavLink to="/#library">
          <span className="nav-icon" aria-hidden="true">
            ▤
          </span>
          Library
        </NavLink>
        <NavLink to="/studio">
          <span className="nav-icon" aria-hidden="true">
            ▶
          </span>
          Studio
        </NavLink>
      </nav>
    </div>
  );
}
