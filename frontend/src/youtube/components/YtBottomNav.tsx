import { NavLink } from "react-router-dom";
import { IconCreate, IconHome, IconShorts, IconSubscriptions, IconYou } from "./Icons";

export function YtBottomNav() {
  return (
    <nav className="yt-bottom-nav" aria-label="Mobile">
      <NavLink to="/" end className={({ isActive }) => `yt-bottom-item${isActive ? " active" : ""}`}>
        {({ isActive }) => (
          <>
            <IconHome filled={isActive} />
            <span>Home</span>
          </>
        )}
      </NavLink>
      <NavLink
        to="/shorts"
        className={({ isActive }) => `yt-bottom-item${isActive ? " active" : ""}`}
      >
        {({ isActive }) => (
          <>
            <IconShorts filled={isActive} />
            <span>Shorts</span>
          </>
        )}
      </NavLink>
      <NavLink to="/create" className="yt-bottom-item create">
        <span className="yt-create-fab">
          <IconCreate size={22} />
        </span>
        <span>Create</span>
      </NavLink>
      <NavLink
        to="/subscriptions"
        className={({ isActive }) => `yt-bottom-item${isActive ? " active" : ""}`}
      >
        {({ isActive }) => (
          <>
            <IconSubscriptions filled={isActive} />
            <span>Subscriptions</span>
          </>
        )}
      </NavLink>
      <NavLink to="/you" className={({ isActive }) => `yt-bottom-item${isActive ? " active" : ""}`}>
        {({ isActive }) => (
          <>
            <IconYou filled={isActive} />
            <span>You</span>
          </>
        )}
      </NavLink>
    </nav>
  );
}
