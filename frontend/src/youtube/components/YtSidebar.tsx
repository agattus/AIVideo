import { NavLink } from "react-router-dom";
import {
  IconHistory,
  IconHome,
  IconLiked,
  IconPlaylist,
  IconShorts,
  IconSubscriptions,
  IconWatchLater,
  IconYou,
} from "./Icons";

type Props = {
  collapsed: boolean;
  openMobile: boolean;
  onNavigate?: () => void;
};

function Item({
  to,
  label,
  icon,
  end,
  onNavigate,
}: {
  to: string;
  label: string;
  icon: (active: boolean) => React.ReactNode;
  end?: boolean;
  onNavigate?: () => void;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) => `yt-nav-item${isActive ? " active" : ""}`}
      onClick={onNavigate}
    >
      {({ isActive }) => (
        <>
          <span className="yt-nav-icon">{icon(isActive)}</span>
          <span className="yt-nav-label">{label}</span>
        </>
      )}
    </NavLink>
  );
}

export function YtSidebar({ collapsed, openMobile, onNavigate }: Props) {
  return (
    <>
      {openMobile ? (
        <button
          type="button"
          className="yt-sidebar-backdrop"
          aria-label="Close menu"
          onClick={onNavigate}
        />
      ) : null}
      <aside
        className={`yt-sidebar${collapsed ? " collapsed" : ""}${openMobile ? " mobile-open" : ""}`}
        aria-label="Primary"
      >
        <div className="yt-sidebar-section">
          <Item
            to="/"
            end
            label="Home"
            onNavigate={onNavigate}
            icon={(a) => <IconHome filled={a} />}
          />
          <Item
            to="/shorts"
            label="Shorts"
            onNavigate={onNavigate}
            icon={(a) => <IconShorts filled={a} />}
          />
          <Item
            to="/subscriptions"
            label="Subscriptions"
            onNavigate={onNavigate}
            icon={(a) => <IconSubscriptions filled={a} />}
          />
          <Item
            to="/you"
            label="You"
            onNavigate={onNavigate}
            icon={(a) => <IconYou filled={a} />}
          />
        </div>

        <div className="yt-sidebar-divider" />

        <div className="yt-sidebar-section">
          <p className="yt-sidebar-heading">You</p>
          <Item
            to="/you#history"
            label="History"
            onNavigate={onNavigate}
            icon={() => <IconHistory />}
          />
          <Item
            to="/you#playlists"
            label="Playlists"
            onNavigate={onNavigate}
            icon={() => <IconPlaylist />}
          />
          <Item
            to="/you#watch-later"
            label="Watch later"
            onNavigate={onNavigate}
            icon={() => <IconWatchLater />}
          />
          <Item
            to="/you#liked"
            label="Liked videos"
            onNavigate={onNavigate}
            icon={() => <IconLiked />}
          />
        </div>

        <div className="yt-sidebar-divider" />

        <div className="yt-sidebar-section">
          <p className="yt-sidebar-heading">Explore</p>
          <NavLink className="yt-nav-item" to="/results?q=music" onClick={onNavigate}>
            <span className="yt-nav-icon text-glyph">♪</span>
            <span className="yt-nav-label">Music</span>
          </NavLink>
          <NavLink className="yt-nav-item" to="/results?q=gaming" onClick={onNavigate}>
            <span className="yt-nav-icon text-glyph">▣</span>
            <span className="yt-nav-label">Gaming</span>
          </NavLink>
          <NavLink className="yt-nav-item" to="/results?q=news" onClick={onNavigate}>
            <span className="yt-nav-icon text-glyph">☰</span>
            <span className="yt-nav-label">News</span>
          </NavLink>
          <NavLink className="yt-nav-item" to="/create" onClick={onNavigate}>
            <span className="yt-nav-icon text-glyph">+</span>
            <span className="yt-nav-label">Create in Studio</span>
          </NavLink>
        </div>
      </aside>
    </>
  );
}
