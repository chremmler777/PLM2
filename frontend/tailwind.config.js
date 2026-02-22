/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: false,
  theme: {
    extend: {
      colors: {
        primary: {
          50: "#f0f9ff",
          500: "#0ea5e9",
          600: "#0284c7",
        },
      },
      backgroundColor: {
        DEFAULT: "#0f172a", // slate-950
      },
      textColor: {
        DEFAULT: "#f1f5f9", // slate-100
      },
    },
  },
  plugins: [],
}
