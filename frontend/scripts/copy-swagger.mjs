// Copies the Swagger UI assets into dist/ so the API documentation works
// without any external CDN.
import { cpSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const src = dirname(require.resolve("swagger-ui-dist/package.json"));
const out = join(process.cwd(), "dist", "swagger");
mkdirSync(out, { recursive: true });
for (const f of ["swagger-ui-bundle.js", "swagger-ui.css"]) cpSync(join(src, f), join(out, f));
writeFileSync(
  join(out, "init.js"),
  `window.ui = SwaggerUIBundle({ url: "/api/openapi.json", dom_id: "#swagger-ui", deepLinking: true,
  requestInterceptor: (req) => { const m = document.cookie.match(/(?:^|; )sleepy_csrf=([^;]+)/);
  if (m) req.headers["X-CSRF-Token"] = decodeURIComponent(m[1]); return req; } });\n`,
);
console.log("swagger assets copied");
