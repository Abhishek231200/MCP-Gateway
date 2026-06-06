import { useState } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { ShieldCheck, ArrowRight, Loader2, Mail, KeyRound } from "lucide-react";
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
      // Dev fallback: show code in UI if email not delivered
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
    <div className="min-h-screen bg-[#0d0d0d] flex items-center justify-center px-4">
      <div className="w-full max-w-sm">

        {/* Logo */}
        <div className="flex items-center justify-center gap-3 mb-10">
          <div className="w-10 h-10 rounded-xl bg-brand-600 flex items-center justify-center">
            <ShieldCheck className="w-5 h-5 text-white" />
          </div>
          <div>
            <p className="text-base font-semibold text-white leading-none">MCP Gateway</p>
            <p className="text-xs text-gray-600 mt-0.5">Agentic Orchestration Platform</p>
          </div>
        </div>

        {/* Card */}
        <div className="bg-[#111111] border border-white/5 rounded-2xl p-8">
          {step === "email" ? (
            <>
              <h1 className="text-lg font-semibold text-white mb-1">Sign in</h1>
              <p className="text-sm text-gray-500 mb-6">
                Enter your email to receive a one-time code.
              </p>
              <form onSubmit={handleRequestOTP} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1.5">
                    Email address
                  </label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600 pointer-events-none" />
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@example.com"
                      autoFocus
                      required
                      className="w-full bg-white/5 border border-white/10 rounded-xl pl-9 pr-4 py-2.5 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-brand-500 transition-colors"
                    />
                  </div>
                </div>
                {error && <p className="text-xs text-red-400">{error}</p>}
                <button
                  type="submit"
                  disabled={loading || !email.trim()}
                  className="w-full flex items-center justify-center gap-2 py-2.5 bg-brand-600 hover:bg-brand-500 disabled:bg-white/5 disabled:text-gray-600 text-white text-sm font-medium rounded-xl transition-colors"
                >
                  {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : (
                    <><span>Continue</span><ArrowRight className="w-4 h-4" /></>
                  )}
                </button>
              </form>
            </>
          ) : (
            <>
              <button
                onClick={() => { setStep("email"); setError(""); setCode(""); setDevCode(null); }}
                className="text-xs text-gray-600 hover:text-gray-300 mb-4 flex items-center gap-1 transition-colors"
              >
                ← {email}
              </button>
              <h1 className="text-lg font-semibold text-white mb-1">Check your email</h1>
              <p className="text-sm text-gray-500 mb-6">
                We sent a 6-digit code to <span className="text-gray-300">{email}</span>
              </p>
              {devCode && (
                <div className="mb-4 p-3 rounded-xl bg-yellow-500/10 border border-yellow-500/20">
                  <p className="text-xs text-yellow-400 font-medium mb-0.5">Demo mode</p>
                  <p className="text-xs text-gray-400">Email not delivered — your code is:</p>
                  <p className="text-2xl font-mono font-bold text-white tracking-widest mt-1">{devCode}</p>
                </div>
              )}
              <form onSubmit={handleVerifyOTP} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1.5">
                    One-time code
                  </label>
                  <div className="relative">
                    <KeyRound className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-600 pointer-events-none" />
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
                      className="w-full bg-white/5 border border-white/10 rounded-xl pl-9 pr-4 py-2.5 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-brand-500 font-mono tracking-widest transition-colors"
                    />
                  </div>
                </div>
                {error && <p className="text-xs text-red-400">{error}</p>}
                <button
                  type="submit"
                  disabled={loading || code.length !== 6}
                  className="w-full flex items-center justify-center gap-2 py-2.5 bg-brand-600 hover:bg-brand-500 disabled:bg-white/5 disabled:text-gray-600 text-white text-sm font-medium rounded-xl transition-colors"
                >
                  {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Sign in"}
                </button>
              </form>
              <p className="text-xs text-gray-600 text-center mt-4">
                Didn't get it?{" "}
                <button
                  onClick={handleRequestOTP}
                  disabled={loading}
                  className="text-gray-400 hover:text-white transition-colors"
                >
                  Resend code
                </button>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
