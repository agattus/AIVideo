import { createContext, useContext } from "react";
import { useCatalog } from "./hooks/useCatalog";
import type { YtVideo } from "./types";

type CatalogValue = {
  videos: YtVideo[];
  byId: Map<string, YtVideo>;
  library: YtVideo[];
  uploads: YtVideo[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  addUpload: (video: YtVideo) => void;
};

const CatalogContext = createContext<CatalogValue | null>(null);

export function CatalogProvider({ children }: { children: React.ReactNode }) {
  const catalog = useCatalog();
  return <CatalogContext.Provider value={catalog}>{children}</CatalogContext.Provider>;
}

export function useYtCatalog() {
  const ctx = useContext(CatalogContext);
  if (!ctx) throw new Error("useYtCatalog must be used within CatalogProvider");
  return ctx;
}
