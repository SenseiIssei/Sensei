import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, Lock, Mail, User as UserIcon } from "lucide-react";
import { authApi } from "@/lib/auth";
import { Logo, Segmented } from "@/components/ui";

const FIELD =
  "h-10 w-full rounded-sm border border-line-strong bg-surface pl-10 pr-3 text-sm text-fg outline-none " +
  "transition-shadow placeholder:text-faint focus:border-accent focus:ring-1 focus:ring-accent/50";

export function AuthPage() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (mode === "register") await authApi.register(email, password, name);
      else await authApi.login(email, password);
      // Back to the chat that sent you here, not the dashboard.
      navigate("/chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-dvh items-center justify-center bg-canvas px-4">
      <div className="animate-fade-in w-full max-w-sm rounded-lg border border-line bg-surface p-8 shadow-pop dark:shadow-none">
        <div className="mb-8 text-center">
          <Logo className="mx-auto mb-4 h-11 w-11" />
          <h1 className="text-xl font-semibold tracking-[-0.01em] text-fg">
            {mode === "login" ? "Sign in to Sensei" : "Create an account"}
          </h1>
          <p className="mt-1 text-[13px] text-muted">For the shared chat on this server.</p>
        </div>

        <div className="mb-6">
          <Segmented
            label="Sign in or sign up"
            value={mode}
            onChange={(next) => {
              setMode(next);
              setError("");
            }}
            options={[
              { value: "login", label: "Sign in" },
              { value: "register", label: "Sign up" },
            ]}
          />
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          {mode === "register" && (
            <div className="relative">
              <UserIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
                aria-label="Name"
                required
                className={FIELD}
              />
            </div>
          )}
          <div className="relative">
            <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="email@example.com"
              aria-label="Email"
              autoComplete="email"
              required
              className={FIELD}
            />
          </div>
          <div className="relative">
            <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === "register" ? "At least 8 characters" : "Password"}
              aria-label="Password"
              autoComplete={mode === "register" ? "new-password" : "current-password"}
              required
              minLength={mode === "register" ? 8 : undefined}
              className={FIELD}
            />
          </div>

          {error && (
            <div role="alert" className="rounded-md border border-danger/25 bg-danger/10 px-3 py-2 text-[13px] text-danger">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="flex h-10 w-full items-center justify-center gap-2 rounded-sm bg-accent text-[13px] font-semibold text-accent-fg transition-colors hover:bg-accent-hover disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>
      </div>
    </div>
  );
}
