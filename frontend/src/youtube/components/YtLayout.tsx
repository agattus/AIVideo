import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { CatalogProvider } from "../CatalogContext";
import { YtBottomNav } from "./YtBottomNav";
import { YtSidebar } from "./YtSidebar";
import { YtTopbar } from "./YtTopbar";

function LayoutShell() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const isWatch = location.pathname.startsWith("/watch/");
  const isShorts = location.pathname.startsWith("/shorts");

  useEffect(() => {
    setMobileOpen(false);
    window.scrollTo(0, 0);
  }, [location.pathname, location.search]);

  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth >= 1313) setMobileOpen(false);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  function toggleMenu() {
    if (window.innerWidth < 1313) {
      setMobileOpen((v) => !v);
    } else {
      setCollapsed((v) => !v);
    }
  }

  return (
    <div
      className={`yt-app${collapsed || isWatch ? " rail" : ""}${isWatch ? " watch-mode" : ""}${isShorts ? " shorts-mode" : ""}`}
    >
      <YtTopbar onMenuClick={toggleMenu} />
      <YtSidebar
        collapsed={collapsed || isWatch}
        openMobile={mobileOpen}
        onNavigate={() => setMobileOpen(false)}
      />
      <main className="yt-main">
        <Outlet />
      </main>
      {!isWatch ? <YtBottomNav /> : null}
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
