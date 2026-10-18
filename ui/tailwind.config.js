/** Tokens from docs/ui-spec.md section 3. */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#0F0E47",
        surface: "#1B1A52",
        raised: "#272757",
        subtle: "#505081",
        accent: { DEFAULT: "#8686AC", text: "#A9A8D9" },
        ink: { DEFAULT: "#F2F2F8", 2: "#B9B8D6" },
        ok: "#6FD3A0",
        warn: "#F2C14E",
        bad: "#FF8A80",
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      fontSize: {
        cap: ["12px", "16px"],
        sm: ["14px", "20px"],
        base: ["16px", "24px"],
        title: ["20px", "28px"],
        section: ["28px", "36px"],
        head: ["40px", "48px"],
      },
      borderRadius: { DEFAULT: "8px" },
    },
  },
  plugins: [],
};
