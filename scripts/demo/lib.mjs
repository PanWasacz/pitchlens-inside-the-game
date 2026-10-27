// Shared helpers for the scripted demos. They drive the studio through its UI
// and the `window.pitchlens` handle (synthetic match only).

import { spawn } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright";

export const URL = process.env.PITCHLENS_URL ?? "http://localhost:5173";

const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";

/**
 * A headless browser for the demos. Newer Edge builds no longer start in Playwright's
 * pipe mode, so Edge is started with a debugging port and attached over CDP; elsewhere
 * Playwright's own Chromium is used.
 */
export async function launch() {
  if (existsSync(EDGE)) {
    const profile = mkdtempSync(join(tmpdir(), "pitchlens-edge-"));
    const port = 9300 + Math.floor(Math.random() * 500);
    const proc = spawn(EDGE, ["--headless=new", "--no-first-run", "--hide-scrollbars", "--mute-audio",
      `--user-data-dir=${profile}`, `--remote-debugging-port=${port}`, "about:blank"], { stdio: "ignore" });
    for (let i = 0; i < 60; i++) {
      try {
        const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
        const close = browser.close.bind(browser);
        browser.close = async () => {
          await close().catch(() => {});
          proc.kill();
        };
        return browser;
      } catch {
        await new Promise((r) => setTimeout(r, 250));
      }
    }
    proc.kill();
  }
  return chromium.launch();
}

export async function openStudio(page) {
  await page.goto(URL);
  await page.waitForFunction(() => window.pitchlens && document.querySelector("#loading.done"), null, { timeout: 60000 });
  await page.waitForTimeout(800);
}

/** Run a function against the app inside the page: app(fn, arg). */
export const app = (page, fn, arg) => page.evaluate(([src, a]) => new Function("app", "arg", `return (${src})(app, arg)`)(window.pitchlens, a), [fn.toString(), arg]);

export const idx = (page, id) => app(page, (a, pid) => a.match.players.findIndex((p) => p.id === pid), id);

export async function seek(page, t) {
  await app(page, (a, s) => a.seek(s), t);
  await page.waitForTimeout(400);
}

export async function select(page, ids) {
  const list = [];
  for (const id of ids) list.push(await idx(page, id));
  await app(page, (a, l) => (a.selected = l), list);
}

export async function toggle(page, key, on) {
  await app(page, (a, [k, v]) => { if (a.toggles[k] !== v) a.toggle(k); }, [key, on]);
}

export async function view(page, v) {
  await app(page, (a, x) => a.setView(x), v);
  await page.waitForTimeout(900);
}

export async function play(page, rate = 1) {
  await app(page, (a, r) => { a.setRate(r); if (!a.playing) a.togglePlay(); }, rate);
}

export async function pause(page) {
  await app(page, (a) => a.pause());
}

export async function insights(page, open) {
  await page.evaluate((o) => {
    const panel = document.querySelector("#insights");
    if (panel.hidden === o) document.querySelector("#insightsBtn").click();
  }, open);
}

export async function audience(page, mode, lang, team = "") {
  await page.click(`[data-audience="${mode}"]`);
  await page.selectOption("#aiLang", lang);
  await page.selectOption("#aiTeam", team);
}

/** Click Explain or Recap and wait for the agents' answer. */
export async function ask(page, which = "#explain") {
  await page.click(which);
  await page.waitForFunction(() => !document.querySelector("#explain").disabled, null, { timeout: 60000 });
  await page.waitForTimeout(300);
}

export async function draw(page, shapes) {
  await app(page, (a, s) => (a.drawings.shapes = s), shapes);
}

/** Remove live cards and the goal/offside banner left over from earlier steps. */
export async function clearOverlays(page) {
  await page.evaluate(() => {
    document.querySelector("#feed").innerHTML = "";
    document.querySelector("#banner").classList.remove("show");
  });
}
