import { useState, type FormEvent } from "react";
import { supabase } from "../lib/supabase";

type Phase = "idle" | "sending" | "sent" | "error";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!supabase) {
      setError("Supabase is not configured in this build.");
      setPhase("error");
      return;
    }
    const trimmed = email.trim();
    if (!trimmed) return;
    setPhase("sending");
    setError(null);
    const redirectTo = `${window.location.origin}/`;
    const { error: authError } = await supabase.auth.signInWithOtp({
      email: trimmed,
      options: { emailRedirectTo: redirectTo },
    });
    if (authError) {
      setError(authError.message);
      setPhase("error");
      return;
    }
    setPhase("sent");
  }

  return (
    <div className="login-gate">
      <div className="login-sky" aria-hidden="true" />
      <div className="login-grain" aria-hidden="true" />
      <section className="login-hero">
        <p className="login-brand">
          S-<span>Studio</span>
        </p>
        {phase === "sent" ? (
          <div className="login-copy login-sent" key="sent">
            <h1>Check your email</h1>
            <p>
              We sent a magic link to <strong>{email.trim()}</strong>. Open it to
              step into your studio.
            </p>
          </div>
        ) : (
          <div className="login-copy" key="form">
            <h1>Films from a spark</h1>
            <p>Sign in with a magic link — no password, just your email.</p>
            <form className="login-form" onSubmit={onSubmit}>
              <label className="sr-only" htmlFor="login-email">
                Email
              </label>
              <input
                id="login-email"
                type="email"
                autoComplete="email"
                placeholder="you@studio.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={phase === "sending"}
              />
              <button type="submit" className="login-cta" disabled={phase === "sending"}>
                {phase === "sending" ? "Sending…" : "Send magic link"}
              </button>
            </form>
            {error ? <p className="login-error">{error}</p> : null}
          </div>
        )}
      </section>
    </div>
  );
}
