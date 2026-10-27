// Records the demo video (under 2 minutes, 1920x1080, synthetic matches only) -> scripts/demo/out/pitchlens-demo.webm
//
//   node video.mjs                                   # local studio (npm run dev + python api/server.py)
//   PITCHLENS_URL=https://<site>.azurewebsites.net node video.mjs   # deployed site with the real model
//
// Captions are burnt in, so the video also works without a voice-over. With a voice-over
// cut into out/<VOICE_DIR>/01.wav ... 10.wav (durations in voice.json; VOICE_DIR defaults to
// "voice"), every segment lasts at least as long as its line, and out/timeline.json records
// the segments so mix.mjs can lay the voice over the picture.

import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import {
  URL as SITE, app, ask, audience, clearOverlays, draw, insights, launch, pause, play, seek, select, toggle, view,
} from "./lib.mjs";

const OUT = new URL("./out/", import.meta.url);
mkdirSync(OUT, { recursive: true });
const outPath = (name) => new URL(name, OUT).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const SIZE = { width: 1920, height: 1080 };
const REPO = "github.com/PanWasacz/pitchlens-inside-the-game";
const VOICE_DIR = process.env.VOICE_DIR ?? "voice";

const browser = await launch();
const context = await browser.newContext({ viewport: SIZE, recordVideo: { dir: outPath(""), size: SIZE } });
const page = await context.newPage();
const t0 = Date.now(); // the recording starts with the page
const wait = (s) => page.waitForTimeout(s * 1000);

const VOICE_FILE = outPath(`${VOICE_DIR}/voice.json`);
const voice = existsSync(VOICE_FILE) ? JSON.parse(readFileSync(VOICE_FILE, "utf8")) : [];
const LEAD = 0.3; // the line starts this long after the picture changes
const TAIL = 0.5; // and the picture holds this long after the line ends
const starts = [];

/**
 * One narrated segment: run its actions, then hold until its voice line has finished.
 * The recorder's clock drifts from wall time, so each segment start also flips an 8x8 px
 * sync mark in the bottom-right corner; mix.mjs finds the flips in the video itself.
 * The mark's colour is kept in sessionStorage so it survives a page reload.
 */
async function seg(n, body) {
  await page.evaluate((k) => {
    const color = k % 2 ? "#ffffff" : "#000000";
    sessionStorage.setItem("plMark", color);
    let el = document.querySelector("#syncMark");
    if (!el) {
      el = document.createElement("div");
      el.id = "syncMark";
      el.style.cssText = "position:fixed;right:0;bottom:0;width:8px;height:8px;z-index:100";
      document.body.append(el);
    }
    el.style.background = color;
  }, n);
  const start = (Date.now() - t0) / 1000;
  starts.push({ n, start: start + LEAD });
  const d = voice[n - 1] ?? 0;
  await body(d);
  const left = start + LEAD + d + TAIL - (Date.now() - t0) / 1000;
  if (left > 0) await wait(left);
}

const CARD_STYLE =
  "position:fixed;inset:0;z-index:99;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;background:#05080f;color:#f4f6fb;text-align:center;font-family:Barlow Condensed,Arial Narrow,sans-serif";
const cardHtml = (t, s) =>
  `<div style="font-size:84px;font-weight:700;letter-spacing:.06em">${t}</div><div style="font:500 30px Inter,system-ui,sans-serif;color:rgba(244,246,251,.7);max-width:1300px;line-height:1.5">${s}</div>`;
const LOGO = 'PITCHLENS <span style="color:#2bf5b6">STUDIO</span>';

// On every page load: restore the sync mark, and cover the loading screen with the
// title card (first load) or the card requested before a match switch.
await context.addInitScript(
  ([style, title]) => {
    document.addEventListener("DOMContentLoaded", () => {
      const mark = sessionStorage.getItem("plMark");
      if (mark) {
        const el = document.createElement("div");
        el.id = "syncMark";
        el.style.cssText = `position:fixed;right:0;bottom:0;width:8px;height:8px;z-index:100;background:${mark}`;
        document.body.append(el);
      }
      const html = sessionStorage.getItem("plCard") ?? (sessionStorage.getItem("plTitled") ? null : title);
      sessionStorage.setItem("plTitled", "1");
      sessionStorage.removeItem("plCard");
      if (html) {
        const el = document.createElement("div");
        el.id = "demoCard";
        el.style.cssText = style;
        el.innerHTML = html;
        document.body.append(el);
      }
    });
  },
  [CARD_STYLE, cardHtml(LOGO, "Telestration and explainable match intelligence for TV pundits and fans<br>Synthetic matches · fictional teams and players")],
);

async function caption(text) {
  await page.evaluate((t) => {
    let el = document.querySelector("#demoCaption");
    if (!el) {
      el = document.createElement("div");
      el.id = "demoCaption";
      el.style.cssText =
        "position:fixed;left:50%;bottom:110px;transform:translateX(-50%);z-index:98;padding:12px 26px;border-radius:10px;background:rgba(5,8,15,.88);color:#fff;font:600 28px Inter,system-ui,sans-serif;max-width:1400px;text-align:center;border:1px solid rgba(43,245,182,.5)";
      document.body.append(el);
    }
    el.textContent = t;
    el.style.display = t ? "block" : "none";
  }, text);
}

/** Load a match (page reload) behind a card; returns once the studio is ready. */
async function openMatch(key, card) {
  if (card) await page.evaluate((h) => sessionStorage.setItem("plCard", h), card);
  await page.goto(`${SITE}${SITE.includes("?") ? "&" : "?"}data=${key}`);
  await page.waitForFunction(() => window.pitchlens && document.querySelector("#loading.done"), null, { timeout: 60000 });
  await toggle(page, "feed", false);
}
const removeCard = () => page.evaluate(() => document.querySelector("#demoCard")?.remove());
const scrollToAnswer = () =>
  page.evaluate(() => document.querySelector("#explain").scrollIntoView({ block: "start", behavior: "smooth" }));

// 1. Title over the first load (the counter-attack scenario): the line starts as soon
// as the card is up, while the match loads behind it.
await page.goto(`${SITE}${SITE.includes("?") ? "&" : "?"}data=transition-attack`, { waitUntil: "domcontentloaded" });
await page.waitForSelector("#demoCard");
await seg(1, async () => {
  await page.waitForFunction(() => window.pitchlens && document.querySelector("#loading.done"), null, { timeout: 60000 });
  await toggle(page, "feed", false);
  await seek(page, 486);
});
await removeCard();

// 2. A scenario and the live feed: the counter-attack goal.
await seg(2, async (d) => {
  await caption("One demo match and three scenarios, all generated by our own simulator");
  await toggle(page, "feed", true);
  await play(page, 1);
  await wait(Math.max(5, d * 0.45));
  await caption("Live feed: goals, sprints, offsides and momentum swings appear as the match plays");
  await wait(Math.max(5, d * 0.6));
  await pause(page);
});
await caption("");

// 3. Back to the demo match: tracking, shapes, tactical view and drawings.
await seg(3, async () => {
  await openMatch("demo", cardHtml("Demo match", "Northbridge Rovers vs Kestrel Bay Athletic"));
  await seek(page, 418);
  await wait(0.8);
  await removeCard();
  await caption("Track players, show team shapes, switch to the tactical view and draw");
  await select(page, ["H09", "A05"]);
  await toggle(page, "distances", true);
  await wait(3);
  await toggle(page, "distances", false);
  await select(page, []);
  await seek(page, 150);
  await toggle(page, "shapeHome", true);
  await toggle(page, "shapeAway", true);
  await view(page, "top");
  const zone = { kind: "zone", pts: [[70, 18], [92, 18], [92, 50], [70, 50]], color: "#FFE14D" };
  await draw(page, [zone, { kind: "arrow", a: [55, 30], b: [80, 22], color: "#FFFFFF" }]);
  await wait(2);
  await view(page, "main");
  await wait(1.5);
});
await draw(page, []);
await toggle(page, "shapeHome", false);
await toggle(page, "shapeAway", false);

// 4. Offside
await seek(page, 208);
await toggle(page, "offside", true);
await seg(4, async (d) => {
  await caption("Offside line at the moment of the pass, with the attacker beyond it");
  await play(page, 1);
  await wait(Math.max(7, d));
  await pause(page);
});
await toggle(page, "offside", false);

// 5. Player focus
await clearOverlays(page);
await toggle(page, "feed", true);
await seek(page, 414);
await select(page, ["H09"]);
await app(page, (a) => a.setFocus(true));
await seg(5, async () => {
  await caption("Player focus: the camera follows one player, with live stats and only their moments");
  await play(page, 2);
  await wait(6);
  await pause(page);
});
await app(page, (a) => a.setFocus(false));
await select(page, []);
await toggle(page, "feed", false);
await clearOverlays(page);

// 6. Possession dynamics chart
await seek(page, 270);
await seg(6, async (d) => {
  await caption("Possession dynamics: who controls the ball, second by second");
  await app(page, (a) => a.toggleMomentum(true));
  await wait(2.5);
  await play(page, 2);
  await wait(Math.max(3, d - 2.5));
  await pause(page);
});
await app(page, (a) => a.toggleMomentum(false));

// 7. AI analyst
await seek(page, 207.4);
await seg(7, async (d) => {
  await caption("AI analyst: four agents on Microsoft Foundry explain why the moment matters");
  await insights(page, true);
  await audience(page, "analyst", "en");
  await ask(page);
  await scrollToAnswer();
  await wait(Math.max(4, d * 0.45));
  await caption("Every claim is backed by computed facts; the Verifier checks numbers, names and logic");
  await page.evaluate(() => {
    const t = document.querySelector(".ai-trace");
    t.open = true;
    t.scrollIntoView({ block: "start", behavior: "smooth" });
  });
  await wait(4);
});

// 8. Personalisation
await seg(8, async (d) => {
  await caption("Same facts, different viewer: a Kestrel Bay fan, in Polish");
  await audience(page, "fan", "pl", "away");
  await ask(page);
  await scrollToAnswer();
  await wait(Math.max(3.5, d * 0.55));
  await caption("…or in Spanish");
  await audience(page, "fan", "es", "away");
  await ask(page);
  await wait(2.5);
});

// 9. Recap, then the match report
await seek(page, 600);
await seg(9, async (d) => {
  await caption("Automated recaps, and a full report for every match");
  await audience(page, "analyst", "en");
  await ask(page, "#recap");
  await scrollToAnswer();
  await wait(Math.max(3, d * 0.3));
  await insights(page, false);
  await app(page, (a) => a.toggleReport(true));
  await page.waitForFunction(() => document.querySelector("#report")?.dataset.loaded === "true", null, { timeout: 30000 });
  await caption("Match report: statistics, top players, shot and heat maps, and a PDF typeset in LaTeX");
  await wait(Math.max(2.5, d * 0.3));
  await page.evaluate(() => {
    const h = [...document.querySelectorAll("#reportOut h3")].find((x) => x.textContent?.startsWith("Shot map"));
    h?.scrollIntoView({ block: "start", behavior: "smooth" });
  });
  await wait(3);
});
await caption("");

// 10. Outro
await page.evaluate(
  ([style, html]) => {
    const el = document.createElement("div");
    el.id = "demoCard";
    el.style.cssText = style;
    el.innerHTML = html;
    document.body.append(el);
  },
  [CARD_STYLE, cardHtml(LOGO, `Microsoft Foundry · Azure App Service · Application Insights · GitHub Actions<br><br>${REPO}`)],
);
await seg(10, () => wait(4));
await wait(1);

const video = page.video();
await context.close();
await browser.close();
const final = outPath("pitchlens-demo.webm");
renameSync(await video.path(), final);
writeFileSync(outPath("timeline.json"), JSON.stringify(starts, null, 1));
console.log("saved", final, `(${((Date.now() - t0) / 1000).toFixed(1)} s)`);
