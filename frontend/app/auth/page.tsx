"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Bot, Loader2 } from "lucide-react";
import { FormEvent, Suspense, useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Mode = "signup" | "login";

function GoogleIcon() {
  return (
    <svg className="google-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.1c-.22-.66-.35-1.36-.35-2.1s.13-1.44.35-2.1V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l3.66-2.84z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06L5.84 9.9C6.71 7.3 9.14 5.38 12 5.38z"
      />
    </svg>
  );
}

function AuthContent() {
  const searchParams = useSearchParams();
  const requestedMode = searchParams.get("mode") === "login" ? "login" : "signup";
  const [mode, setMode] = useState<Mode>(requestedMode);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setMode(requestedMode);
  }, [requestedMode]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);
    const endpoint = mode === "signup" ? "/api/auth/register" : "/api/auth/login";
    const body =
      mode === "signup"
        ? { first_name: firstName || null, last_name: lastName || null, email, password }
        : { email, password };

    try {
      const response = await fetch(`${API_URL}${endpoint}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || "Authentication failed");
      }
      window.location.href = "/dashboard";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  function googleLogin() {
    window.location.href = `${API_URL}/api/auth/google/start`;
  }

  const signup = mode === "signup";

  return (
    <main className="grid-page auth-page">
      <section className="auth-card">
        <div className="auth-top">
          <Link className="brand" href="/">
            <span className="brand-mark">
              <Bot size={20} />
            </span>
            <span>Rebly AI</span>
          </Link>
          <h1>{signup ? "Create your account" : "Welcome back"}</h1>
          <p>{signup ? "Fill in the details to get started." : "Sign in to open your AI workspace."}</p>
        </div>

        <form className="auth-form" onSubmit={submit}>
          {signup && (
            <div className="name-grid">
              <label className="field">
                <span>
                  First name <small>Optional</small>
                </span>
                <input value={firstName} onChange={(event) => setFirstName(event.target.value)} placeholder="First name" />
              </label>
              <label className="field">
                <span>
                  Last name <small>Optional</small>
                </span>
                <input value={lastName} onChange={(event) => setLastName(event.target.value)} placeholder="Last name" />
              </label>
            </div>
          )}

          <label className="field">
            Email address
            <input
              required
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
            />
          </label>

          <label className="field">
            Password
            <input
              required
              minLength={8}
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="••••••••"
              autoComplete={signup ? "new-password" : "current-password"}
            />
          </label>

          {error && <div className="auth-error">{error}</div>}

          <button className="auth-submit" type="submit" disabled={loading}>
            {loading ? <Loader2 size={18} /> : signup ? "Continue" : "Sign in"}
          </button>

          <button className="google-button" type="button" onClick={googleLogin}>
            <GoogleIcon /> Continue with Google
          </button>
        </form>

        <div className="auth-switch">
          {signup ? "Already have an account? " : "Need an account? "}
          <button type="button" onClick={() => setMode(signup ? "login" : "signup")}>
            {signup ? "Sign in" : "Get started"}
          </button>
        </div>
        <div className="auth-foot">Secured by Rebly AI</div>
      </section>
    </main>
  );
}

export default function AuthPage() {
  return (
    <Suspense
      fallback={
        <main className="grid-page auth-page">
          <section className="auth-card">
            <div className="auth-top">
              <span className="brand">
                <span className="brand-mark">
                  <Bot size={20} />
                </span>
                <span>Rebly AI</span>
              </span>
              <Loader2 size={22} />
            </div>
          </section>
        </main>
      }
    >
      <AuthContent />
    </Suspense>
  );
}
