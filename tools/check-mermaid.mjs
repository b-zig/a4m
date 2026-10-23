// Parse every ```mermaid block under the given directory with the real Mermaid parser.
// Usage: npm ci --prefix tools && node tools/check-mermaid.mjs docs
import fs from "node:fs";
import path from "node:path";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>");
Object.assign(globalThis, { window: dom.window, document: dom.window.document, DOMParser: dom.window.DOMParser, Element: dom.window.Element });
const { default: mermaid } = await import("mermaid");
mermaid.initialize({ startOnLoad: false });

function* markdownFiles(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) yield* markdownFiles(full);
    else if (entry.name.endsWith(".md")) yield full;
  }
}

let checked = 0, failed = 0;
for (const file of markdownFiles(process.argv[2] ?? "docs")) {
  const text = fs.readFileSync(file, "utf8");
  for (const block of text.matchAll(/```mermaid\n([\s\S]*?)```/g)) {
    checked++;
    try {
      await mermaid.parse(block[1]);
    } catch (err) {
      failed++;
      console.error(`FAIL ${file}\n${String(err.message ?? err)}\n`);
    }
  }
}
console.log(`mermaid: ${checked - failed}/${checked} diagrams parse`);
process.exit(failed ? 1 : 0);
