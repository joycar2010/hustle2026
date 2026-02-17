/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#3b82f6',
        secondary: '#10b981',
        warning: '#f59e0b',
        danger: '#ef4444',
        info: '#64748b',
      },
    },
  },
  plugins: [],
}
