import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // CIE Design System — matches DESIGN.md
        primary:                    "#003e78",
        "primary-container":        "#0a559f",
        "primary-fixed":            "#d5e3ff",
        "primary-fixed-dim":        "#a7c8ff",
        "on-primary":               "#ffffff",
        "on-primary-fixed":         "#001b3b",
        secondary:                  "#4d5f7e",
        "secondary-container":      "#c8dbff",
        "on-secondary":             "#ffffff",
        surface:                    "#f8f9ff",
        "surface-bright":           "#f8f9ff",
        "surface-dim":              "#cbdbf5",
        "surface-container-lowest": "#ffffff",
        "surface-container-low":    "#eff4ff",
        "surface-container":        "#e5eeff",
        "surface-container-high":   "#dce9ff",
        "surface-container-highest":"#d3e4fe",
        "surface-variant":          "#d3e4fe",
        "on-surface":               "#0b1c30",
        "on-surface-variant":       "#424751",
        "inverse-surface":          "#213145",
        "inverse-on-surface":       "#eaf1ff",
        outline:                    "#727782",
        "outline-variant":          "#c2c6d3",
        error:                      "#ba1a1a",
        "error-container":          "#ffdad6",
        "on-error":                 "#ffffff",
        tertiary:                   "#672e00",
        "tertiary-container":       "#8a4000",
        "on-tertiary":              "#ffffff",
        background:                 "#f8f9ff",
        "on-background":            "#0b1c30",
      },
      fontFamily: {
        headline: ["Inter", "sans-serif"],
        body:     ["Inter", "sans-serif"],
        label:    ["Inter", "sans-serif"],
      },
      borderRadius: {
        DEFAULT: "0.125rem",
        lg:      "0.25rem",
        xl:      "0.5rem",
        full:    "0.75rem",
      },
    },
  },
  plugins: [],
};

export default config;
