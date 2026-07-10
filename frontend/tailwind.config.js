/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        p: {
          bg:           "var(--p-bg)",
          "bg-subtle":  "var(--p-bg-subtle)",
          surface:      "var(--p-surface)",
          "surface-2":  "var(--p-surface-2)",
          text:         "var(--p-text)",
          "text-muted": "var(--p-text-muted)",
          "text-faint": "var(--p-text-faint)",
          accent: ({ opacityValue }) =>
            `oklch(var(--p-accent-l) var(--p-accent-c) var(--p-accent-h)${opacityValue !== undefined ? ` / ${opacityValue}` : ""})`,
          "accent-mid": ({ opacityValue }) =>
            `oklch(var(--p-accent-mid-l) var(--p-accent-mid-c) var(--p-accent-mid-h)${opacityValue !== undefined ? ` / ${opacityValue}` : ""})`,
          "accent-soft":"var(--p-accent-soft)",
          border:       "var(--p-border)",
          "border-mid": "var(--p-border-mid)",
          success:      "var(--p-success)",
          warning:      "var(--p-warning)",
          error:        "var(--p-error)",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      backdropBlur: {
        glass: "12px",
      },
      keyframes: {
        "fade-up": {
          "0%":   { opacity: "0", transform: "translateY(10px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "shimmer": {
          "0%":   { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition:  "200% 0" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.3s ease-out",
        "shimmer": "shimmer 2s linear infinite",
      },
    },
  },
  plugins: [],
};
