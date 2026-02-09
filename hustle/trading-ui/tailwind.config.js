/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'bg-primary': '#121212',
        'bg-secondary': '#1E1E1E',
        'text-primary': '#FFFFFF',
        'text-secondary': '#B0B0B0',
        'success': '#4CAF50',
        'danger': '#F44336',
        'warning': '#FF9800',
        'info': '#2196F3',
        'border': '#333333',
      },
      fontFamily: {
        'sans': ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}

