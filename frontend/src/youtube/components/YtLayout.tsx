import { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { CatalogProvider } from "../CatalogContext";
import { YtBottomNav } from "./YtBottomNav";
import { YtTopbar } from "./YtTopbar";

function LayoutShell() {
  const location = useLocation();
  const isWatch = location.pathname.startsWith("/watch/");
  const isClips = location.pathname.startsWith("/clips");

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname, location.search]);

  return (
    <div
      className={`yt-app${isWatch ? " watch-mode" : ""}${isClips ? " shorts-mode" : ""}`}
    >
      <YtTopbar />
      <main className="yt-main">
        <Outlet />
      </main>
      <YtBottomNav />
    </div>
  );
}

export function YtLayout() {
  return (
    <CatalogProvider>
      <LayoutShell />
    </CatalogProvider>
  );
}
