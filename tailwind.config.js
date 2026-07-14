/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./static/js/**/*.js",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: 'rgb(var(--color-bg) / <alpha-value>)',
        surface: 'rgb(var(--color-surface) / <alpha-value>)',
        ink: 'rgb(var(--color-ink) / <alpha-value>)',
        muted: 'rgb(var(--color-ink-muted) / <alpha-value>)',
        line: 'rgb(var(--color-line) / <alpha-value>)',
        marker: 'rgb(var(--color-marker) / <alpha-value>)',
        'marker-stroke': 'var(--marker-stroke)',
        accent: 'rgb(var(--color-accent) / <alpha-value>)',
        primary: {
          50: 'rgb(var(--color-surface) / <alpha-value>)',
          100: 'var(--marker-stroke)',
          200: 'rgb(var(--color-marker) / <alpha-value>)',
          300: 'rgb(var(--color-marker) / <alpha-value>)',
          400: 'rgb(var(--color-accent) / <alpha-value>)',
          500: 'rgb(var(--color-accent) / <alpha-value>)',
          600: 'rgb(var(--color-accent) / <alpha-value>)',
          700: 'rgb(var(--color-ink) / <alpha-value>)',
          800: 'rgb(var(--color-ink) / <alpha-value>)',
          900: 'rgb(var(--color-ink) / <alpha-value>)',
        }
      },
      fontFamily: {
        display: ['Fraunces', 'Georgia', 'serif'],
        passage: ['Literata', 'Georgia', 'serif'],
        ui: ['"Libre Franklin"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        card: '0 10px 30px rgb(90 65 36 / 0.08)',
      },
      keyframes: {
        'marker-draw': {
          '0%': { transform: 'rotate(var(--marker-rotate, -1.5deg)) scaleX(0)' },
          '100%': { transform: 'rotate(var(--marker-rotate, -1.5deg)) scaleX(1)' },
        },
      },
      animation: {
        'marker-draw': 'marker-draw 300ms ease-out both',
      },
    }
  },
  plugins: [],
}
