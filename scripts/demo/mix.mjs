// Lays the voice-over (out/<VOICE_DIR>/NN.wav) over the recorded video -> out/pitchlens-demo.mp4
// (H.264 + AAC, for YouTube). Lines whose recording is missing are left silent (draft).
//
//   node mix.mjs            # needs ffmpeg on PATH, or FFMPEG=<path to ffmpeg.exe>
//
// The browser recorder's clock drifts from wall time, so segment starts are read from the
// video itself: video.mjs flips an 8x8 px mark in the bottom-right corner (black/white) at
// the start of every segment. The mark is painted over in the output.

import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";

const out = (name) => new URL(`./out/${name}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const ffmpeg = process.env.FFMPEG ?? "ffmpeg";
const LEAD = 0.3; // same as video.mjs: the line starts this long after the cut
const timeline = JSON.parse(readFileSync(out("timeline.json"), "utf8"));
const video = out("pitchlens-demo.webm");
const VOICE_DIR = process.env.VOICE_DIR ?? "voice";

// Brightness of the sync mark in every frame.
const log = spawnSync(
  ffmpeg,
  ["-hide_banner", "-i", video, "-vf", "crop=4:4:in_w-6:in_h-6,signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"],
  { encoding: "utf8", maxBuffer: 256 * 1024 * 1024 },
).stderr;
let state = null;
let pts = 0;
const flips = [];
for (const line of log.split(/\r?\n/)) {
  const p = /pts_time:([\d.]+)/.exec(line);
  if (p) pts = Number(p[1]);
  const y = /YAVG=([\d.]+)/.exec(line);
  if (!y) continue;
  const v = Number(y[1]);
  // Mark is white (Y ~235) on odd segments, black (Y ~16) on even ones; ignore frames in between.
  const s = v > 180 ? "w" : v < 40 ? "b" : null;
  if (s && s !== state) {
    if (s === "w" ? flips.length % 2 === 0 : flips.length % 2 === 1) flips.push(pts);
    state = s;
  }
}
if (flips.length !== timeline.length) {
  throw new Error(`found ${flips.length} segment marks in the video, expected ${timeline.length}`);
}
console.log("segment starts in video:", flips.map((t) => t.toFixed(2)).join(" "));

// The recorder also loses time while the match animates, so a segment can come out shorter
// than its line. Such segments get their last frame held until the line has finished.
const TAIL = 0.5;
const total = Number(
  spawnSync(ffmpeg.replace(/ffmpeg(\.exe)?$/i, "ffprobe$1"), ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video], { encoding: "utf8" }).stdout,
);
const voiceLen = JSON.parse(readFileSync(out(`${VOICE_DIR}/voice.json`), "utf8"));
const pieces = [{ from: 0, to: flips[0], hold: 0 }];
const starts = [];
let cursor = flips[0];
flips.forEach((from, i) => {
  const to = flips[i + 1] ?? total;
  const need = LEAD + voiceLen[timeline[i].n - 1] + TAIL;
  const hold = Math.max(0, need - (to - from));
  starts.push(cursor + LEAD);
  pieces.push({ from, to, hold });
  cursor += to - from + hold;
});
console.log("held frames (s):", pieces.slice(1).map((p) => p.hold.toFixed(1)).join(" "), `· final length ${cursor.toFixed(1)} s`);

const filters = ["[0:v]drawbox=x=iw-10:y=ih-10:w=10:h=10:color=0x05080f:t=fill,split=" + pieces.length + pieces.map((_, i) => `[s${i}]`).join("")];
pieces.forEach((p, i) => {
  const pad = p.hold > 0 ? `,tpad=stop_mode=clone:stop_duration=${p.hold.toFixed(3)}` : "";
  filters.push(`[s${i}]trim=start=${p.from}:end=${p.to},setpts=PTS-STARTPTS${pad}[p${i}]`);
});
filters.push(`${pieces.map((_, i) => `[p${i}]`).join("")}concat=n=${pieces.length}:v=1:a=0[pic]`);

const args = ["-y", "-hide_banner", "-loglevel", "error", "-i", video];
const lines = [];
timeline.forEach(({ n }, i) => {
  const wav = out(`${VOICE_DIR}/${String(n).padStart(2, "0")}.wav`);
  if (!existsSync(wav)) {
    console.log(`line ${n}: no recording yet, left silent`);
    return;
  }
  args.push("-i", wav);
  const ms = Math.round(starts[i] * 1000);
  filters.push(`[${lines.length + 1}:a]adelay=${ms}|${ms}[v${lines.length}]`);
  lines.push(n);
});
filters.push(`${lines.map((_, i) => `[v${i}]`).join("")}amix=inputs=${lines.length}:normalize=0:dropout_transition=0,apad[voice]`);
args.push(
  "-filter_complex", filters.join(";"),
  "-map", "[pic]", "-map", "[voice]",
  "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "25",
  "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
  "-movflags", "+faststart", "-shortest",
  out("pitchlens-demo.mp4"),
);
execFileSync(ffmpeg, args, { stdio: "inherit" });
console.log("saved", out("pitchlens-demo.mp4"));
