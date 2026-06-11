/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: false,
  theme: {
    extend: {
      fontFamily: {
        sans: ['Geist', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['Geist Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      colors: {
        primary: {
          50: "#f0f9ff",
          500: "#0ea5e9",
          600: "#0284c7",
        },
      },
      boxShadow: {
        // navy-tinted elevation instead of pure black
        panel: "0 1px 2px 0 rgba(2, 6, 23, 0.5), 0 4px 16px -4px rgba(2, 6, 23, 0.4)",
        lift: "0 8px 24px -6px rgba(2, 6, 23, 0.6)",
      },
    },
  },
  plugins: [],
}
