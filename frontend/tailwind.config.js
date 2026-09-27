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
      fontSize: {
        // The type floor: nothing in the UI is smaller than 11 px.
        '2xs': ['11px', { lineHeight: '14px' }],
      },
      keyframes: {
        'dialog-in': {
          from: { opacity: '0', transform: 'translateY(4px) scale(0.98)' },
          to: { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
      },
      animation: {
        'dialog-in': 'dialog-in 160ms cubic-bezier(0.22, 1, 0.36, 1)',
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
