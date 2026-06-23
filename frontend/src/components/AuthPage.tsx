import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Mail, Lock, User as UserIcon, Loader2, Sparkles } from "lucide-react";
import { authApi } from "@/lib/auth";

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
      if (mode === "register") {
        await authApi.register(email, password, name);
      } else {
        await authApi.login(email, password);
      }
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4 surreal-bg">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="orb orb-1" />
        <div className="orb orb-2" />
        <div className="orb orb-3" />
      </div>

      <div className="glass rounded-2xl p-8 w-full max-w-md relative z-10">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 mb-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-sensei-500 to-sensei-700 flex items-center justify-center glow-text">
              <span className="text-white font-bold text-2xl">S</span>
            </div>
          </div>
          <h1 className="text-2xl font-bold text-white">Sensei</h1>
          <p className="text-sm text-gray-500 mt-1">
            {mode === "login" ? "Welcome back! 💚" : "Join the future of AI 🚀"}
          </p>
        </div>

        {/* Tab switcher */}
        <div className="flex gap-2 mb-6 p-1 glass rounded-xl">
          <button
            onClick={() => { setMode("login"); setError(""); }}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all ${
              mode === "login" ? "bg-sensei-600 text-white" : "text-gray-400 hover:text-white"
            }`}
          >
            Sign In
          </button>
          <button
            onClick={() => { setMode("register"); setError(""); }}
            className={`flex-1 py-2 rounded-lg text-sm font-medium transition-all ${
              mode === "register" ? "bg-sensei-600 text-white" : "text-gray-400 hover:text-white"
            }`}
          >
            Sign Up
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === "register" && (
            <div className="relative">
              <UserIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Your name"
                required
                className="w-full glass text-white text-sm rounded-xl pl-10 pr-4 py-3 border border-gray-700/50 focus:border-sensei-600/50 focus:outline-none"
              />
            </div>
          )}
          <div className="relative">
            <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="email@example.com"
              required
              className="w-full glass text-white text-sm rounded-xl pl-10 pr-4 py-3 border border-gray-700/50 focus:border-sensei-600/50 focus:outline-none"
            />
          </div>
          <div className="relative">
            <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600" />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={mode === "register" ? "At least 8 characters" : "Password"}
              required
              minLength={mode === "register" ? 8 : undefined}
              className="w-full glass text-white text-sm rounded-xl pl-10 pr-4 py-3 border border-gray-700/50 focus:border-sensei-600/50 focus:outline-none"
            />
          </div>

          {error && (
            <div className="px-4 py-3 rounded-lg bg-red-950/30 border border-red-900/50 text-red-400 text-sm">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-sensei-600 hover:bg-sensei-700 text-white font-medium transition-colors disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                {mode === "login" ? "Sign In" : "Create Account"}
              </>
            )}
          </button>
        </form>

        <p className="text-xs text-gray-600 text-center mt-6">
          {mode === "login" ? "New here? " : "Already have an account? "}
          <button
            onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}
            className="text-sensei-500 hover:text-sensei-400"
          >
            {mode === "login" ? "Create an account" : "Sign in instead"}
          </button>
        </p>
      </div>
    </div>
  );
}
