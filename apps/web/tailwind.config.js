/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Sky-blue / cyan accent — fresh, distinct, techy
        brand: {
          50:  "#f0f9ff",
          100: "#e0f2fe",
          200: "#bae6fd",
          300: "#7dd3fc",
          400: "#38bdf8",
          500: "#0ea5e9",
          600: "#0284c7",
          700: "#0369a1",
          800: "#075985",
          900: "#0c4a6e",
          950: "#082f49",
        },
        // Layered dark-navy surfaces (noticeably lighter than before)
        surface: {
          0: "#0d1117",
          1: "#161c26",
          2: "#1c2335",
          3: "#232c42",
          4: "#2a3450",
          5: "#32405f",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "Consolas", "monospace"],
      },
      backgroundImage: {
        "dot-grid": "radial-gradient(rgba(14,165,233,0.10) 1px, transparent 1px)",
      },
      backgroundSize: {
        "dot-24": "24px 24px",
      },
      boxShadow: {
        "glow-sm":  "0 0 12px rgba(14,165,233,0.18)",
        "glow":     "0 0 24px rgba(14,165,233,0.22)",
        "glow-lg":  "0 0 48px rgba(14,165,233,0.28)",
        "card":     "0 1px 3px rgba(0,0,0,0.35), 0 0 0 1px rgba(255,255,255,0.05)",
        "card-hover": "0 4px 20px rgba(0,0,0,0.4), 0 0 0 1px rgba(14,165,233,0.15)",
      },
      animation: {
        "pulse-slow":  "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "slide-up":    "slideUp 0.18s ease-out",
        "fade-in":     "fadeIn 0.15s ease-out",
        "float":       "float 3s ease-in-out infinite",
      },
      keyframes: {
        slideUp: {
          from: { opacity: "0", transform: "translateY(6px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        fadeIn: {
          from: { opacity: "0" },
          to:   { opacity: "1" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%":      { transform: "translateY(-4px)" },
        },
      },
    },
  },
  plugins: [],
};
