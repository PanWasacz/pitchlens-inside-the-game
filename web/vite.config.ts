import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, join, normalize, resolve } from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";
import { defineConfig, type Plugin } from "vite";

// Local-only footage and CV output live in ../match (git-ignored, never built).
const MATCH_DIR = resolve(__dirname, "../match");
const TYPES: Record<string, string> = {
  ".mp4": "video/mp4",
  ".json": "application/json",
  ".jsonl": "application/x-ndjson",
};

function serveLocalMatch(req: IncomingMessage, res: ServerResponse, next: () => void) {
  const path = normalize(join(MATCH_DIR, decodeURIComponent((req.url ?? "/").split("?")[0])));
  if (!path.startsWith(MATCH_DIR) || !existsSync(path) || !statSync(path).isFile()) return next();
  const size = statSync(path).size;
  const type = TYPES[extname(path)] ?? "application/octet-stream";
  const range = /bytes=(\d*)-(\d*)/.exec(req.headers.range ?? "");
  if (range) {
    // Byte ranges let the <video> element seek.
    const start = range[1] ? Number(range[1]) : 0;
    const end = range[2] ? Number(range[2]) : size - 1;
    res.writeHead(206, {
      "Content-Type": type,
      "Content-Range": `bytes ${start}-${end}/${size}`,
      "Content-Length": end - start + 1,
      "Accept-Ranges": "bytes",
    });
    createReadStream(path, { start, end }).pipe(res);
  } else {
    res.writeHead(200, { "Content-Type": type, "Content-Length": size, "Accept-Ranges": "bytes" });
    createReadStream(path).pipe(res);
  }
}

function devOnly(): Plugin {
  return {
    name: "pitchlens-dev",
    configureServer(server) {
      server.middlewares.use("/local", serveLocalMatch);
    },
  };
}

export default defineConfig({
  plugins: [devOnly()],
  server: {
    host: true,
    // The explain agents run in api/ (python api/local_server.py, or `swa start` / `func start`).
    proxy: { "/api": "http://localhost:7071" },
  },
});
