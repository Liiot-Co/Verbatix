/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        p: {
          bg:           "#F5F1EC",
          "bg-subtle":  "#EDE8E0",
          surface:      "#FFFFFF",
          "surface-2":  "#F0EBE3",
          text:         "#2C2622",
          "text-muted": "#7A6F68",
          "text-faint": "#B0A499",
          accent:       "#7B5EA7",
          "accent-mid": "#9B7DC8",
          "accent-soft":"#C4B0E0",
          border:       "rgba(60,40,20,0.10)",
          "border-mid": "rgba(60,40,20,0.18)",
          success:      "#3D7A5F",
          warning:      "#9C7020",
          error:        "#A03030",
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
