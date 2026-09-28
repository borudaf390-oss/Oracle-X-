import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "#0B0D10",
        panel: "#14171C",
        border: "#242A33",
        "border-bright": "#333B49",
        text: {
          primary: "#E8EAED",
          secondary: "#8B93A7",
          muted: "#565E6D",
        },
        signal: "#E8A33D",
        long: "#4FD1C5",
        short: "#F0554C",
        block: "#F0554C",
        pass: "#4FD1C5",
      },
      fontFamily: {
        sans: ["var(--font-plex-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-plex-mono)", "ui-monospace", "monospace"],
      },
      fontSize: {
        "data-lg": ["1.75rem", { lineHeight: "1.1", letterSpacing: "-0.01em" }],
        "data-md": ["1.125rem", { lineHeight: "1.2" }],
        "data-sm": ["0.8125rem", { lineHeight: "1.3" }],
      },
    },
  },
  plugins: [],
};
export default config;
