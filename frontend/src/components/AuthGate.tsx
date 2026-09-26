import { useEffect, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import {
  getSession,
  setAccessToken,
  supabase,
  supabaseConfigured,
} from "../lib/supabase";
import { LoginPage } from "./LoginPage";

export function AuthGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(!supabaseConfigured);
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    if (!supabaseConfigured || !supabase) {
      setAccessToken(null);
      setReady(true);
      return;
    }

    let cancelled = false;

    void (async () => {
      const current = await getSession();
      if (cancelled) return;
      setSession(current);
      setAccessToken(current?.access_token ?? null);
      setReady(true);
    })();

    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next);
      setAccessToken(next?.access_token ?? null);
      setReady(true);
    });

    return () => {
      cancelled = true;
      data.subscription.unsubscribe();
    };
  }, []);

  if (!ready) {
    return (
      <div className="login-gate login-loading">
        <p className="login-brand">
          S-<span>Studio</span>
        </p>
        <p className="login-copy">Opening the gate…</p>
      </div>
    );
  }

  if (supabaseConfigured && !session) {
    return <LoginPage />;
  }

  return <>{children}</>;
}
