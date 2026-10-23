module.exports = {
  content: ["./app/templates/**/*.html", "./app/static/js/**/*.js"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#fdf2f8",
          100: "#fce7f3",
          500: "#d5105c",
          700: "#a33957",
          800: "#943d56",
          900: "#752d42",
        },
      },
      fontFamily: {
        sans: ["Segoe UI", "Roboto", "Helvetica Neue", "sans-serif"],
      },
      keyframes: {
        pulseHeart: {
          "0%, 100%": { transform: "scale(1)" },
          "50%": { transform: "scale(1.15)" },
        },
        floatSlow: {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%": { transform: "translateY(-8px)" },
        },
      },
      animation: {
        "pulse-heart": "pulseHeart 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        float: "floatSlow 4s ease-in-out infinite",
      },
    },
  },
};
