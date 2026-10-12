import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const webRoot = path.resolve(import.meta.dirname, "..");
const html = fs.readFileSync(path.join(webRoot, "index.html"), "utf8");
const main = fs.readFileSync(path.join(webRoot, "src", "main.ts"), "utf8");
const styles = fs.readFileSync(path.join(webRoot, "src", "styles.css"), "utf8");
const theme = fs.readFileSync(path.join(webRoot, "src", "studio", "theme.css"), "utf8");
const preferences = fs.readFileSync(path.join(webRoot, "src", "studio", "preferences.ts"), "utf8");

test("Motion Studio declares adaptive light and dark appearances", () => {
  assert.match(html, /name="color-scheme" content="light dark"/);
  assert.match(main, /data-theme-preference/);
  assert.match(main, /virea\.theme\.v1/);
  assert.match(theme, /:root\[data-theme="light"\]/);
  assert.match(theme, /:root\[data-theme="dark"\]/);
  assert.match(preferences, /prefers-color-scheme: dark/);
});

test("workspace layouts consume a single shared HeroUI theme", () => {
  assert.match(theme, /@import "@heroui\/styles"/);
  for (const file of ["styles.css", "character/style.css", "vrchat.css", "setup.css"]) {
    const layout=fs.readFileSync(path.join(webRoot,"src",file),"utf8");
    assert.doesNotMatch(layout, /:root\s*\{/);
    assert.doesNotMatch(layout, /#[0-9a-f]{3,8}(?:\s|;|\))/i);
  }
  assert.match(styles, /prefers|@media/);
});
