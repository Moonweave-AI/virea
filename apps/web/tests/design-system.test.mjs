import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const webRoot = path.resolve(import.meta.dirname, "..");
const html = fs.readFileSync(path.join(webRoot, "index.html"), "utf8");
const main = fs.readFileSync(path.join(webRoot, "src", "main.ts"), "utf8");
const styles = fs.readFileSync(path.join(webRoot, "src", "styles.css"), "utf8");

test("Motion Studio declares adaptive light and dark appearances", () => {
  assert.match(html, /name="color-scheme" content="light dark"/);
  assert.match(main, /data-theme-preference/);
  assert.match(main, /virea\.theme\.v1/);
  assert.match(styles, /:root\[data-theme="light"\]/);
  assert.match(styles, /:root\[data-theme="dark"\]/);
  assert.match(styles, /prefers-color-scheme: dark/);
});

test("Motion Studio uses a wide responsive workbench and balanced comparison stage", () => {
  assert.match(styles, /\.page-frame \{ width: min\(1920px/);
  assert.match(styles, /\.studio-grid \{[^}]*minmax\(700px, 1fr\)/s);
  assert.match(styles, /\.motion-comparison \{[^}]*aspect-ratio: 16 \/ 7/s);
  assert.match(styles, /@media \(max-width: 920px\)/);
  assert.match(styles, /@media \(max-width: 680px\)/);
});
