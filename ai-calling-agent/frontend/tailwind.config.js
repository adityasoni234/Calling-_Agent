/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // The brand blue, unchanged — everything else is tuned around it.
        brand: {
          50: '#eef4ff',
          100: '#d9e6ff',
          200: '#bcd2ff',
          300: '#8eb4ff',
          400: '#598bff',
          500: '#3364fb',
          600: '#1d43f0',
          700: '#1832dc',
          800: '#1a2cb2',
          900: '#1b2c8c',
          950: '#141d5c',
        },
        // A slightly warmer neutral than slate: less clinical under the blue.
        ink: {
          50: '#f7f8fa',
          100: '#eef0f4',
          200: '#dfe3ea',
          300: '#c6ccd8',
          400: '#98a1b3',
          500: '#6b7488',
          600: '#4e5668',
          700: '#3b4252',
          800: '#252b38',
          900: '#161b26',
          950: '#0d1017',
        },
      },
      fontFamily: {
        sans: ['Inter var', 'Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        // Tighter tracking on display sizes; loose text at small sizes reads better.
        '2xs': ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.02em' }],
      },
      borderRadius: {
        xl: '0.875rem',
        '2xl': '1.125rem',
      },
      boxShadow: {
        // Two-layer shadows: a tight contact shadow plus a soft ambient one.
        card: '0 1px 2px 0 rgb(13 16 23 / 0.04), 0 4px 16px -4px rgb(13 16 23 / 0.06)',
        lift: '0 2px 4px 0 rgb(13 16 23 / 0.05), 0 12px 32px -8px rgb(13 16 23 / 0.12)',
        glow: '0 0 0 1px rgb(29 67 240 / 0.12), 0 8px 24px -6px rgb(29 67 240 / 0.28)',
      },
      backgroundImage: {
        'brand-sheen': 'linear-gradient(135deg, #1d43f0 0%, #3364fb 55%, #598bff 100%)',
        'ink-deep': 'linear-gradient(180deg, #161b26 0%, #0d1017 100%)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.28s cubic-bezier(0.16, 1, 0.3, 1) both',
        shimmer: 'shimmer 1.6s infinite',
      },
    },
  },
  plugins: [],
}
