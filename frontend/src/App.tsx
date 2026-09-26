import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { AuthGate } from "./components/AuthGate";
import { HomePage } from "./pages/HomePage";
import { StudioPage } from "./pages/StudioPage";

export default function App() {
  return (
    <AuthGate>
      <AppShell>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/studio" element={<StudioPage />} />
          <Route path="/studio/:jobId" element={<StudioPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
    </AuthGate>
  );
}
