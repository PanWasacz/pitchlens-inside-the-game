// README screenshots of the synthetic demo match -> docs/img/*.png
// Needs the studio (npm run dev in web/) and, for the AI panel, the API (python api/server.py).

import { mkdirSync } from "node:fs";
import { app, ask, audience, clearOverlays, draw, insights, launch, openStudio, pause, play, seek, select, toggle, view } from "./lib.mjs";

const OUT = new URL("../../docs/img/", import.meta.url);
mkdirSync(OUT, { recursive: true });

const browser = await launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
await openStudio(page);
await toggle(page, "feed", false);
const shot = async (name) => {
  await page.waitForTimeout(500);
  await page.screenshot({ path: new URL(`${name}.png`, OUT).pathname.replace(/^\/([A-Za-z]:)/, "$1") });
  console.log("saved", name);
};

// 1. Broadcast view, two tracked players with cards, trails and their distance.
await seek(page, 418);
await play(page, 1);
await page.waitForTimeout(2500);
await pause(page);
await select(page, ["H09", "A05"]);
await toggle(page, "distances", true);
await shot("tv-tracking");
await toggle(page, "distances", false);
await select(page, []);

// 2. Offside at the moment of the pass (03:32).
await seek(page, 212.4);
await toggle(page, "offside", true);
await shot("offside");
await toggle(page, "offside", false);

// 3. Tactical view with both team shapes and a pundit's drawings.
await seek(page, 150);
await toggle(page, "shapeHome", true);
await toggle(page, "shapeAway", true);
await view(page, "top");
await draw(page, [
  { kind: "zone", pts: [[70, 18], [92, 18], [92, 50], [70, 50]], color: "#FFE14D" },
  { kind: "arrow", a: [55, 30], b: [80, 22], color: "#FFFFFF" },
]);
await shot("tactical-shapes");
await draw(page, []);
await toggle(page, "shapeHome", false);
await toggle(page, "shapeAway", false);
await view(page, "main");

// 4. Player focus + live feed + momentum strip, around the 07:03 equaliser.
await toggle(page, "feed", true);
await seek(page, 414);
await select(page, ["H09"]);
await app(page, (a) => a.setFocus(true));
await play(page, 2);
await page.waitForTimeout(5200);
await pause(page);
await shot("focus-feed");
await app(page, (a) => a.setFocus(false));
await select(page, []);
await toggle(page, "feed", false);
await clearOverlays(page);

// 5. AI analyst: explanation with evidence and the agent trace.
await seek(page, 207.4);
await insights(page, true);
await audience(page, "analyst", "en");
await ask(page);
await page.evaluate(() => {
  document.querySelector(".ai-trace").open = true;
  document.querySelector("#explain").scrollIntoView({ block: "start" });
});
await shot("ai-analyst");

// 6. Same moment for a Polish fan, and a recap.
await audience(page, "fan", "pl", "home");
await ask(page);
await shot("ai-fan-pl");
await seek(page, 600);
await audience(page, "analyst", "en");
await ask(page, "#recap");
await shot("ai-recap");

await browser.close();
