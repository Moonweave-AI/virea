import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [tailwindcss()],
  // The production UI is served by FastAPI's StaticFiles mount at /app.
  // Keep emitted JS/CSS URLs inside that mount instead of the site root.
  base: "/app/",
  build: { rollupOptions: { input: ["index.html", "character.html", "vrchat.html", "setup.html"] } },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        ws: true,
      },
    },
  },
});
