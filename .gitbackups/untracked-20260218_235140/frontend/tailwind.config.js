/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: '#F0B90B',
        dark: {
          100: '#1E2329',
          200: '#181A20',
          300: '#0B0E11',
        },
        green: {
          500: '#0ECB81',
          600: '#0DB774',
        },
        red: {
          500: '#F6465D',
          600: '#E03D52',
        },
      },
    },
  },
  plugins: [],
}
