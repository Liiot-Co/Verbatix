/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        heading: ["Givonic", "Satoshi", "system-ui", "sans-serif"],
        subtitle: ["Satoshi", "system-ui", "sans-serif"],
        body: ["Open Sans", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      colors: {
        p: {
          bg: "var(--p-bg)",
          "bg-subtle": "var(--p-bg-subtle)",
          surface: "var(--p-surface)",
          "surface-2": "var(--p-surface-2)",
          text: "var(--p-text)",
          "text-muted": "var(--p-text-muted)",
          "text-faint": "var(--p-text-faint)",
          accent: ({ opacityValue }) =>
            opacityValue
              ? `oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / ${opacityValue})`
              : "oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h))",
          "accent-mid": ({ opacityValue }) =>
            opacityValue
              ? `oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h) / ${opacityValue})`
              : "oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h))",
          "accent-soft": "var(--p-accent-soft)",
          border: "var(--p-border)",
          "border-mid": "var(--p-border-mid)",
          success: "var(--p-success)",
          warning: "var(--p-warning)",
          error: "var(--p-error)",
          "accent-glow": "oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.15)",
          "accent-mid-glow": "oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h) / 0.12)",
        },
      },
      boxShadow: {
        "card": "0 1px 3px 0 oklch(0.05 0.02 280 / 0.08), 0 1px 2px -1px oklch(0.05 0.02 280 / 0.06)",
        "card-hover": "0 8px 24px -8px oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.25), 0 4px 12px -4px oklch(0.05 0.02 280 / 0.08)",
        "card-active": "0 2px 8px -2px oklch(0.05 0.02 280 / 0.12)",
        "glow": "0 0 40px -10px oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.25)",
        "glow-mid": "0 0 40px -10px oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h) / 0.2)",
        "inner-glow": "inset 0 0 60px oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.05)",
        "focus": "0 0 0 2px oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.35)",
      },
      borderRadius: {
        "card": "16px",
        "card-sm": "12px",
        "pill": "9999px",
      },
      transitionDuration: {
        "instant": "50ms",
        "micro": "100ms",
        "fast": "150ms",
        "normal": "200ms",
        "slow": "300ms",
        "gentle": "400ms",
        "ambient": "700ms",
      },
      transitionTimingFunction: {
        "out-expo": "cubic-bezier(0.19, 1, 0.22, 1)",
        "out-circ": "cubic-bezier(0.05, 0.7, 0.1, 1)",
        "out-back": "cubic-bezier(0.34, 1.56, 0.64, 1)",
        "in-out-circ": "cubic-bezier(0.85, 0, 0.15, 1)",
        "spring-gentle": "cubic-bezier(0.22, 1, 0.36, 1)",
        "spring-bouncy": "cubic-bezier(0.34, 1.56, 0.64, 1)",
      },
      animation: {
        "shimmer": "shimmer 2s ease-in-out infinite",
        "shimmer-slow": "shimmer 3s ease-in-out infinite",
        "fade-in": "fadeIn 200ms ease-out forwards",
        "fade-out": "fadeOut 150ms ease-in forwards",
        "scale-in": "scaleIn 200ms ease-out forwards",
        "scale-out": "scaleOut 150ms ease-in forwards",
        "slide-in-right": "slideInRight 250ms ease-out forwards",
        "slide-in-left": "slideInLeft 250ms ease-out forwards",
        "slide-out-right": "slideOutRight 200ms ease-in forwards",
        "slide-out-left": "slideOutLeft 200ms ease-in forwards",
        "slide-up": "slideUp 300ms ease-out forwards",
        "slide-down": "slideDown 300ms ease-out forwards",
        "pop-in": "popIn 300ms cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
        "pop-out": "popOut 200ms ease-in forwards",
        "pulse-soft": "pulseSoft 2.5s ease-in-out infinite",
        "float": "float 4s ease-in-out infinite",
        "glow-pulse": "glowPulse 3s ease-in-out infinite",
        "stagger-in": "staggerIn 300ms ease-out forwards",
        "accordion-down": "accordionDown 200ms ease-out forwards",
        "accordion-up": "accordionUp 200ms ease-in forwards",
        "spin-slow": "spin 3s linear infinite",
        "wiggle": "wiggle 500ms ease-in-out",
        "success-pop": "successPop 400ms cubic-bezier(0.34, 1.56, 0.64, 1) forwards",
        "error-shake": "errorShake 400ms ease-in-out",
        "focus-ring": "focusRing 200ms ease-out forwards",
        "ambient-drift": "ambientDrift 20s ease-in-out infinite",
        "gradient-x": "gradientShift 4s ease-in-out infinite",
        "gradient-x-slow": "gradientShift 7s ease-in-out infinite",
        "gradient-xy": "gradientDrift 8s ease-in-out infinite",
        "gradient-xy-slow": "gradientDrift 12s ease-in-out infinite",
        "border-glow-spin": "borderGlowSpin 3s linear infinite",
        "border-glow-spin-slow": "borderGlowSpin 6s linear infinite",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "200% 0" },
          "100%": { backgroundPosition: "-200% 0" },
        },
        gradientShift: {
          "0%, 100%": { backgroundPosition: "0% 50%" },
          "50%": { backgroundPosition: "100% 50%" },
        },
        gradientDrift: {
          "0%": { backgroundPosition: "0% 0%" },
          "25%": { backgroundPosition: "100% 0%" },
          "50%": { backgroundPosition: "100% 100%" },
          "75%": { backgroundPosition: "0% 100%" },
          "100%": { backgroundPosition: "0% 0%" },
        },
        borderGlowSpin: {
          "0%": { transform: "rotate(0deg)" },
          "100%": { transform: "rotate(360deg)" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        fadeOut: {
          "0%": { opacity: "1" },
          "100%": { opacity: "0" },
        },
        scaleIn: {
          "0%": { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        scaleOut: {
          "0%": { opacity: "1", transform: "scale(1)" },
          "100%": { opacity: "0", transform: "scale(0.95)" },
        },
        slideInRight: {
          "0%": { opacity: "0", transform: "translateX(16px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        slideInLeft: {
          "0%": { opacity: "0", transform: "translateX(-16px)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        slideOutRight: {
          "0%": { opacity: "1", transform: "translateX(0)" },
          "100%": { opacity: "0", transform: "translateX(16px)" },
        },
        slideOutLeft: {
          "0%": { opacity: "1", transform: "translateX(0)" },
          "100%": { opacity: "0", transform: "translateX(-16px)" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideDown: {
          "0%": { opacity: "0", transform: "translateY(-12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        popIn: {
          "0%": { opacity: "0", transform: "scale(0.92)" },
          "60%": { opacity: "1", transform: "scale(1.03)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        popOut: {
          "0%": { opacity: "1", transform: "scale(1)" },
          "100%": { opacity: "0", transform: "scale(0.92)" },
        },
        pulseSoft: {
          "0%, 100%": { opacity: "0.4" },
          "50%": { opacity: "0.8" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-6px)" },
        },
        glowPulse: {
          "0%, 100%": { opacity: "0.15", filter: "blur(40px)" },
          "50%": { opacity: "0.3", filter: "blur(60px)" },
        },
        staggerIn: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        accordionDown: {
          "0%": { height: "0", opacity: "0" },
          "100%": { height: "var(--radix-accordion-content-height)", opacity: "1" },
        },
        accordionUp: {
          "0%": { height: "var(--radix-accordion-content-height)", opacity: "1" },
          "100%": { height: "0", opacity: "0" },
        },
        wiggle: {
          "0%, 100%": { transform: "rotate(0deg)" },
          "25%": { transform: "rotate(-3deg)" },
          "75%": { transform: "rotate(3deg)" },
        },
        successPop: {
          "0%": { opacity: "0", transform: "scale(0.8) rotate(-5deg)" },
          "50%": { opacity: "1", transform: "scale(1.1) rotate(2deg)" },
          "100%": { opacity: "1", transform: "scale(1) rotate(0deg)" },
        },
        errorShake: {
          "0%, 100%": { transform: "translateX(0)" },
          "20%": { transform: "translateX(-6px)" },
          "40%": { transform: "translateX(6px)" },
          "60%": { transform: "translateX(-4px)" },
          "80%": { transform: "translateX(4px)" },
        },
        focusRing: {
          "0%": { boxShadow: "0 0 0 0 oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.4)" },
          "100%": { boxShadow: "0 0 0 3px oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0)" },
        },
        ambientDrift: {
          "0%, 100%": { transform: "translate(0, 0) rotate(0deg)" },
          "25%": { transform: "translate(2%, -1%) rotate(0.5deg)" },
          "50%": { transform: "translate(-1%, 2%) rotate(-0.3deg)" },
          "75%": { transform: "translate(1%, 1%) rotate(0.2deg)" },
        },
      },
      backgroundImage: {
        "gradient-accent": "linear-gradient(135deg, oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h)), oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h)))",
        "gradient-accent-reverse": "linear-gradient(315deg, oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h)), oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h)))",
        "gradient-card-1": "linear-gradient(135deg, #fde4f4, #deeeff)",
        "gradient-card-2": "linear-gradient(135deg, #d8f5e8, #fdf8cc)",
        "gradient-card-3": "linear-gradient(135deg, #fef0d6, #e6e0ff)",
        "gradient-card-4": "linear-gradient(135deg, #fef0e0, #ede0fc)",
        "gradient-card-5": "linear-gradient(135deg, #dff5f0, #fce0f5)",
        "gradient-logo": "linear-gradient(135deg, #7C5FBF, #E8893A)",
        "radial-accent-tl": "radial-gradient(60vw 60vh circle at 0% 0%, oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.06), transparent 55%)",
        "radial-accent-tr": "radial-gradient(60vw 60vh circle at 100% 0%, oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.05), transparent 55%)",
        "radial-accent-bl": "radial-gradient(50vw 50vh circle at 0% 100%, oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h) / 0.05), transparent 50%)",
        "radial-accent-br": "radial-gradient(50vw 50vh circle at 100% 100%, oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h) / 0.04), transparent 50%)",
        "radial-glow-tl": "radial-gradient(520px circle at 100% 0%, oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h) / 0.07), transparent 55%)",
        "radial-glow-bl": "radial-gradient(520px circle at 0% 100%, oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h) / 0.06), transparent 55%)",
      },
      backgroundSize: {
        "200%": "200% 100%",
      },
      zIndex: {
        "ambient": "-10",
        "toast": "100",
        "modal": "1000",
        "command-palette": "1100",
      },
      backdropBlur: {
        "glass": "12px",
      },
    },
  },
  plugins: [],
}