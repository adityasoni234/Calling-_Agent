/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Deep evergreen rather than an electric blue: restrained, and it reads
        // as considered rather than loud next to a lot of white.
        brand: {
          50: '#f0f6f3',
          100: '#dbeae3',
          200: '#b9d5c8',
          300: '#8bb8a5',
          400: '#5a9680',
          500: '#3a7a63',
          600: '#2a614e',
          700: '#224f40',
          800: '#1d4035',
          900: '#19352d',
          950: '#0d1f1a',
        },
        // Warm greys on a paper ground. A cool slate under this much white
        // looks clinical; the warmth is what makes it read as printed.
        ink: {
          50: '#faf9f7',
          100: '#f2f0ec',
          200: '#e5e1da',
          300: '#cdc7bd',
          400: '#9c948a',
          500: '#746c62',
          600: '#57514a',
          700: '#423d38',
          800: '#2b2824',
          900: '#1a1816',
          950: '#0f0e0d',
        },
      },
      fontFamily: {
        // A real serif for headings. This is the single biggest signal that
        // the product is considered rather than generated from a template.
        display: ['Newsreader', 'ui-serif', 'Georgia', 'serif'],
        sans: ['Inter var', 'Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        // Tighter tracking on display sizes; loose text at small sizes reads better.
        '2xs': ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.02em' }],
      },
      borderRadius: {
        // Softer than before. Editorial layouts lean on whitespace and rules,
        // so corners stop doing the work.
        xl: '0.625rem',
        '2xl': '0.875rem',
      },
      boxShadow: {
        // Almost nothing. Separation comes from hairline rules and space, not
        // from floating every panel off the page.
        card: '0 1px 2px 0 rgb(26 24 22 / 0.03)',
        lift: '0 1px 3px 0 rgb(26 24 22 / 0.06), 0 8px 24px -10px rgb(26 24 22 / 0.14)',
        glow: '0 1px 2px 0 rgb(26 24 22 / 0.08)',
      },
      backgroundImage: {
        'brand-sheen': 'linear-gradient(135deg, #224f40 0%, #2a614e 60%, #3a7a63 100%)',
        'ink-deep': 'linear-gradient(180deg, #faf9f7 0%, #f2f0ec 100%)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
        'slide-in': {
          from: { transform: 'translateX(-100%)' },
          to: { transform: 'translateX(0)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.28s cubic-bezier(0.16, 1, 0.3, 1) both',
        shimmer: 'shimmer 1.6s infinite',
        'slide-in': 'slide-in 0.22s cubic-bezier(0.16, 1, 0.3, 1) both',
      },
    },
  },
  plugins: [],
}
