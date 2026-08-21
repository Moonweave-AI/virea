import { defineConfig } from "vite";

export default defineConfig({
  // The production UI is served by FastAPI's StaticFiles mount at /app.
  // Keep emitted JS/CSS URLs inside that mount instead of the site root.
  base: "/app/",
});
