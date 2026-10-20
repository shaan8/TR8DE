/** Tokens from the TR8DE design (dark green workspace). Contrast is kept at WCAG AA for every text colour. */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#111411",
        surface: "#151915",
        raised: "#1c2318",
        subtle: "#343e2c",
        line: "#2a3029",
        accent: { DEFAULT: "#c4df9b", text: "#c4df9b", deep: "#25351a", soft: "#242b20" },
        ink: { DEFAULT: "#e6e9e0", 2: "#a3ab9b" },
        ok: "#a9d37f",
        warn: "#d9c27f",
        bad: "#eba08b",
      },
      fontFamily: {
        sans: ['"DM Sans"', "system-ui", "sans-serif"],
        display: ["Manrope", '"DM Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      fontSize: {
        micro: ["11px", "16px"],
        cap: ["12px", "17px"],
        sm: ["13px", "20px"],
        base: ["14px", "22px"],
        title: ["17px", "24px"],
        section: ["26px", "34px"],
        head: ["34px", "40px"],
      },
      borderRadius: { DEFAULT: "7px" },
    },
  },
  plugins: [],
};
