import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { HomePage } from "./pages/HomePage";
import { StudioPage } from "./pages/StudioPage";
import { YtLayout } from "./youtube/components/YtLayout";
import { YtHomePage } from "./youtube/pages/YtHomePage";
import { YtSearchPage } from "./youtube/pages/YtSearchPage";
import { YtShortsPage } from "./youtube/pages/YtShortsPage";
import { YtSubscriptionsPage } from "./youtube/pages/YtSubscriptionsPage";
import { YtWatchPage } from "./youtube/pages/YtWatchPage";
import { YtYouPage } from "./youtube/pages/YtYouPage";

export default function App() {
  return (
    <Routes>
      <Route element={<YtLayout />}>
        <Route path="/" element={<YtHomePage />} />
        <Route path="/watch/:videoId" element={<YtWatchPage />} />
        <Route path="/clips" element={<YtShortsPage />} />
        <Route path="/following" element={<YtSubscriptionsPage />} />
        <Route path="/you" element={<YtYouPage />} />
        <Route path="/results" element={<YtSearchPage />} />
        <Route path="/shorts" element={<Navigate to="/clips" replace />} />
        <Route path="/subscriptions" element={<Navigate to="/following" replace />} />
      </Route>

      <Route
        path="/create"
        element={
          <AppShell>
            <HomePage />
          </AppShell>
        }
      />
      <Route
        path="/studio"
        element={
          <AppShell>
            <StudioPage />
          </AppShell>
        }
      />
      <Route
        path="/studio/:jobId"
        element={
          <AppShell>
            <StudioPage />
          </AppShell>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
