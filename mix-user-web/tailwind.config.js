/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
    "./src-admin/**/*.{vue,js,ts,jsx,tsx}",
    "./src-www/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#F0B90B',
          hover: '#E0A800',
          light: '#FFF8E1',
        },
        dark: {
          50: '#2B3139',
          100: '#1E2329',
          200: '#181A20',
          300: '#0B0E11',
        },
        success: {
          DEFAULT: '#0ECB81',
          dark: '#0DB774',
        },
        danger: {
          DEFAULT: '#F6465D',
          dark: '#E03D52',
        },
        warning: '#FF9800',
        info: '#2196F3',
        text: {
          primary: '#FFFFFF',
          secondary: '#B7BDC6',
          tertiary: '#848E9C',
          disabled: '#5E6673',
        },
        border: {
          primary: '#2B3139',
          secondary: '#1E2329',
          focus: '#F0B90B',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['Roboto Mono', 'Courier New', 'monospace'],
      },
    },
  },
  plugins: [],
}
