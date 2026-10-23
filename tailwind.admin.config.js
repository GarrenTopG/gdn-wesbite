module.exports = {
  content: ["./app/templates/**/*.html", "./app/static/js/**/*.js"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#fff1f8",
          100: "#ffe4f2",
          500: "#FF2E93",
          600: "#E0257F",
          700: "#C61D69",
          800: "#9B1E59",
          900: "#4A0D2C",
        },
        canvas: {
          950: "#09090B",
          900: "#121215",
          800: "#18181B",
          700: "#27272A",
        },
      },
      fontFamily: {
        sans: ["Segoe UI", "Roboto", "Helvetica Neue", "sans-serif"],
      },
    },
  },
};
