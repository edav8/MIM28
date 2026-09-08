// Real JavaScript syntax check on the dc-script block, using the engine itself.
// The Python checker catches unbalanced delimiters; this catches everything else
// (a stray comma in a bad place, a reserved word as a bare key, broken escapes).
import { readFileSync } from "node:fs";

for (const page of ["index.html", "accounting.html"]) {
const html = readFileSync(new URL(`../${page}`, import.meta.url), "utf8");
const open = html.match(/<script[^>]*\bdata-dc-script\b[^>]*>/);
if (!open) {
  console.error(`error: [${page}] no <script data-dc-script> block found`);
  process.exit(1);
}
const start = open.index + open[0].length;
const end = html.indexOf("</script>", start);
if (end === -1) {
  console.error(`error: [${page}] <script data-dc-script> is never closed`);
  process.exit(1);
}
const body = html.slice(start, end);

try {
  new Function(body);
} catch (e) {
  console.error(`error: [${page}] the logic block is not valid JavaScript\n  ${e.name}: ${e.message}`);
  process.exit(1);
}
console.log(`OK — ${page} parses (${body.length.toLocaleString()} chars).`);
}
