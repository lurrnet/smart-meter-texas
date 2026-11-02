import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
const manifest = JSON.parse(read("./public/manifest.webmanifest"));
assert.equal(manifest.display, "standalone");
assert.equal(manifest.scope, "/");
for (const size of ["192x192","512x512"]) {
  const icon = manifest.icons.find(i => i.sizes === size && i.type === "image/png");
  assert.ok(icon, `Missing PNG ${size}`);
  assert.ok(existsSync(new URL("./public" + icon.src, import.meta.url)));
}
const sw = read("./public/sw.js");
assert.match(sw, /request\.mode === "navigate"/);
assert.match(sw, /request\.method !== "GET"/);
assert.match(sw, /\/assets/);
assert.doesNotMatch(sw, /cache\.addAll\s*\(/);
const html = read("./index.html");
assert.match(html, /manifest\.webmanifest/);
assert.match(html, /apple-touch-icon/);
assert.match(html, /pwa-register\.js/);
console.log("PWA static safety checks passed");
