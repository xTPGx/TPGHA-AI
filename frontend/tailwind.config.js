/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Near-black ChatGPT-style surfaces.
        surface: {
          DEFAULT: "#0a0a0a",
          raised: "#171717",
          overlay: "#212121",
          border: "#2a2a2a",
        },
        // Monochrome accent (replaces the old sky/blue brand). Used as a dark
        // neutral button base with white text.
        brand: {
          DEFAULT: "#343541",
          dark: "#262730",
        },
        // Light accent for primary actions (ChatGPT-style near-white send).
        accent: {
          DEFAULT: "#f5f5f5",
          muted: "#d4d4d4",
        },
      },
    },
  },
  plugins: [],
};
