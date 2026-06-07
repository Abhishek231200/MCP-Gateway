import { useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { ShieldCheck, ArrowRight, Loader2, Mail, KeyRound, Sparkles } from "lucide-react";
import { useAuth, type AuthUser } from "@/contexts/AuthContext";

type Step = "email" | "otp";

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [devCode, setDevCode] = useState<string | null>(null);

  const handleRequestOTP = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setLoading(true);
    setError("");
    try {
      const { data } = await axios.post("/api/auth/request-otp", { email: email.trim() });
      if (data.dev_code) setDevCode(data.dev_code);
      setStep("otp");
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOTP = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    setLoading(true);
    setError("");
    try {
      const { data } = await axios.post<{ token: string; user: AuthUser }>(
        "/api/auth/verify-otp",
        { email: email.trim(), code: code.trim() }
      );
      login(data.token, data.user);
      navigate("/workflows", { replace: true });
    } catch (err) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "Invalid code");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4 relative overflow-hidden"
      style={{ background: "var(--bg)" }}>

      {/* Background glow orbs */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-96 h-96 rounded-full"
          style={{
            background: "radial-gradient(circle, rgba(14,165,233,0.12) 0%, transparent 70%)",
            filter: "blur(40px)",
          }} />
        <div className="absolute bottom-1/4 left-1/3 w-64 h-64 rounded-full"
          style={{
            background: "radial-gradient(circle, rgba(99,102,241,0.08) 0%, transparent 70%)",
            filter: "blur(40px)",
          }} />
        {/* Dot grid */}
        <div className="absolute inset-0 opacity-40"
          style={{
            backgroundImage: "radial-gradient(rgba(14,165,233,0.1) 1px, transparent 1px)",
            backgroundSize: "28px 28px",
          }} />
      </div>

      <div className="w-full max-w-sm relative z-10 animate-slide-up">

        {/* Logo */}
        <div className="flex flex-col items-center gap-3 mb-8">
          <div className="w-12 h-12 rounded-2xl flex items-center justify-center"
            style={{
              background: "linear-gradient(135deg,#0ea5e9,#0284c7)",
              boxShadow: "0 0 32px rgba(14,165,233,0.4), 0 0 0 1px rgba(14,165,233,0.2)",
            }}>
            <ShieldCheck className="w-6 h-6 text-white" />
          </div>
          <div className="text-center">
            <p className="text-lg font-semibold tracking-tight" style={{ color: "var(--text-high)", letterSpacing: "-0.02em" }}>
              MCP Gateway
            </p>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-low)" }}>
              Agentic Orchestration Platform
            </p>
          </div>
        </div>

        {/* Card */}
        <div className="rounded-2xl overflow-hidden"
          style={{
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            boxShadow: "0 0 0 1px rgba(14,165,233,0.05), 0 24px 64px rgba(0,0,0,0.5)",
          }}>

          {/* Top accent bar */}
          <div className="h-0.5" style={{ background: "linear-gradient(90deg, transparent, #0ea5e9, #0284c7, transparent)" }} />

          <div className="p-8">
            {step === "email" ? (
              <>
                <h1 className="text-lg font-semibold mb-1 tracking-tight" style={{ color: "var(--text-high)", letterSpacing: "-0.02em" }}>
                  Welcome back
                </h1>
                <p className="text-sm mb-6" style={{ color: "var(--text-mid)" }}>
                  Sign in with your team email to continue.
                </p>
                <form onSubmit={handleRequestOTP} className="space-y-4">
                  <div>
                    <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-mid)" }}>
                      Email address
                    </label>
                    <div className="relative">
                      <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none" style={{ color: "var(--text-low)" }} />
                      <input
                        type="email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        placeholder="you@yourteam.com"
                        autoFocus
                        required
                        className="input pl-9 text-sm"
                      />
                    </div>
                  </div>
                  {error && <p className="text-xs text-rose-400">{error}</p>}
                  <button
                    type="submit"
                    disabled={loading || !email.trim()}
                    className="btn-primary w-full"
                  >
                    {loading
                      ? <Loader2 className="w-4 h-4 animate-spin" />
                      : <><span>Continue</span><ArrowRight className="w-4 h-4" /></>
                    }
                  </button>
                </form>
              </>
            ) : (
              <>
                <button
                  onClick={() => { setStep("email"); setError(""); setCode(""); setDevCode(null); }}
                  className="flex items-center gap-1.5 text-xs mb-5 transition-colors"
                  style={{ color: "var(--text-low)" }}
                  onMouseOver={e => (e.currentTarget.style.color = "var(--text-high)")}
                  onMouseOut={e => (e.currentTarget.style.color = "var(--text-low)")}
                >
                  ← {email}
                </button>
                <h1 className="text-lg font-semibold mb-1 tracking-tight" style={{ color: "var(--text-high)", letterSpacing: "-0.02em" }}>
                  Check your email
                </h1>
                <p className="text-sm mb-6" style={{ color: "var(--text-mid)" }}>
                  We sent a 6-digit code to{" "}
                  <span style={{ color: "var(--text-high)" }}>{email}</span>
                </p>

                {devCode && (
                  <div className="mb-5 p-4 rounded-xl"
                    style={{ background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.2)" }}>
                    <div className="flex items-center gap-2 mb-2">
                      <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                      <p className="text-xs font-semibold text-amber-400">Demo Mode</p>
                    </div>
                    <p className="text-xs mb-2" style={{ color: "var(--text-mid)" }}>
                      Email delivery failed — use this code:
                    </p>
                    <p className="text-3xl font-mono font-bold tracking-[0.3em]" style={{ color: "var(--text-high)" }}>
                      {devCode}
                    </p>
                  </div>
                )}

                <form onSubmit={handleVerifyOTP} className="space-y-4">
                  <div>
                    <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-mid)" }}>
                      One-time code
                    </label>
                    <div className="relative">
                      <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 pointer-events-none" style={{ color: "var(--text-low)" }} />
                      <input
                        type="text"
                        inputMode="numeric"
                        pattern="[0-9]{6}"
                        maxLength={6}
                        value={code}
                        onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                        placeholder="000000"
                        autoFocus
                        required
                        className="input pl-9 text-sm font-mono tracking-[0.25em] text-center"
                      />
                    </div>
                  </div>
                  {error && <p className="text-xs text-rose-400">{error}</p>}
                  <button
                    type="submit"
                    disabled={loading || code.length !== 6}
                    className="btn-primary w-full"
                  >
                    {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Sign in →"}
                  </button>
                </form>

                <p className="text-xs text-center mt-5" style={{ color: "var(--text-low)" }}>
                  Didn't receive it?{" "}
                  <button
                    onClick={handleRequestOTP as unknown as React.MouseEventHandler}
                    disabled={loading}
                    className="transition-colors underline underline-offset-2"
                    style={{ color: "var(--text-mid)" }}
                    onMouseOver={e => (e.currentTarget.style.color = "#38bdf8")}
                    onMouseOut={e => (e.currentTarget.style.color = "var(--text-mid)")}
                  >
                    Resend code
                  </button>
                </p>
              </>
            )}
          </div>
        </div>

        {/* Footer */}
        <p className="text-center text-[11px] mt-6" style={{ color: "var(--text-low)" }}>
          Access is restricted to registered team members only.
        </p>
      </div>
    </div>
  );
}
