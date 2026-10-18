// Renders every screen state from its fixture at 1440 and 390, saves screenshots to reports/ui/,
// and runs axe. Fixtures replay audit.jsonl and transcripts: no model or chain calls.
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";
import path from "node:path";

const OUT = path.resolve("../reports/ui");
fs.mkdirSync(OUT, { recursive: true });
const WIDTHS = [{ w: 1440, h: 900 }, { w: 390, h: 844 }];

// Same list as GET /api/fixtures; regenerate with: curl -s 127.0.0.1:8000/api/fixtures > tests/fixtures.json
const list = JSON.parse(fs.readFileSync(new URL("./fixtures.json", import.meta.url), "utf8"));

for (const f of list) {
  for (const { w, h } of WIDTHS) {
    test(`${String(f.n).padStart(2, "0")} ${f.name} @${w}`, async ({ page }) => {
      const external = [];
      page.on("request", (r) => {
        const u = new URL(r.url());
        if (!["127.0.0.1", "localhost", "fonts.googleapis.com", "fonts.gstatic.com"].includes(u.hostname)) external.push(r.url());
      });
      await page.setViewportSize({ width: w, height: h });
      await page.goto(`/?fixture=${f.name}`);
      await expect(page.getByRole("heading", { name: "Tiwala" })).toBeVisible();
      await page.waitForLoadState("networkidle");
      await page.evaluate(() => document.fonts.ready);
      const file = `${String(f.n).padStart(2, "0")}-${f.name}-${w}.png`;
      await page.screenshot({ path: path.join(OUT, file), fullPage: true });

      const scroll = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(scroll, "no horizontal page scroll").toBeLessThanOrEqual(0);
      expect(external, "no chain or model calls").toEqual([]);

      const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const bad = axe.violations.filter((v) => ["serious", "critical"].includes(v.impact));
      fs.writeFileSync(path.join(OUT, `axe-${f.name}-${w}.json`), JSON.stringify(axe.violations.map((v) => ({
        id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.map((n) => n.target.join(" ")).slice(0, 5),
      })), null, 2));
      expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(", ")}`)).toEqual([]);
    });
  }
}

// Negotiation workspace and supplier console, replayed from reports/negotiation (recorded local demos).
const NEG = path.resolve("../reports/negotiation");
const negList = fs.existsSync(NEG) ? fs.readdirSync(NEG).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5)).sort() : [];
const views = negList.flatMap((name) => [{ name, view: "negotiate", heading: "Tiwala" }]).concat(
  negList.includes("neg_success") ? [{ name: "neg_success", view: "supplier", heading: "Supplier console" }] : []);

for (const v of views) {
  for (const { w, h } of WIDTHS) {
    test(`${v.view} ${v.name} @${w}`, async ({ page }) => {
      const external = [];
      page.on("request", (r) => {
        const u = new URL(r.url());
        if (!["127.0.0.1", "localhost", "fonts.googleapis.com", "fonts.gstatic.com"].includes(u.hostname)) external.push(r.url());
      });
      await page.setViewportSize({ width: w, height: h });
      await page.goto(`/?view=${v.view}&fixture=${v.name}`);
      await expect(page.getByRole("heading", { name: v.heading })).toBeVisible();
      await page.waitForLoadState("networkidle");
      await page.evaluate(() => document.fonts.ready);
      await page.screenshot({ path: path.join(OUT, `${v.view}-${v.name}-${w}.png`), fullPage: true });
      const scroll = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(scroll, "no horizontal page scroll").toBeLessThanOrEqual(0);
      expect(external, "no chain or model calls").toEqual([]);
      const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const bad = axe.violations.filter((x) => ["serious", "critical"].includes(x.impact));
      fs.writeFileSync(path.join(OUT, `axe-${v.view}-${v.name}-${w}.json`), JSON.stringify(axe.violations.map((x) => ({
        id: x.id, impact: x.impact, help: x.help, nodes: x.nodes.map((n) => n.target.join(" ")).slice(0, 5),
      })), null, 2));
      expect(bad.map((x) => `${x.id}: ${x.nodes.map((n) => n.target).join(", ")}`)).toEqual([]);
    });
  }
}
