
import { pathToFileURL } from "node:url";
import puppeteer from "puppeteer-core";

const html = process.argv[2];
const pdf = process.argv[3];
const chrome = process.argv[4];

const browser = await puppeteer.launch({
  executablePath: chrome,
  headless: true,
  args: ["--disable-gpu", "--no-sandbox"],
});
const page = await browser.newPage();
await page.goto(pathToFileURL(html).href, { waitUntil: "networkidle0", timeout: 120000 });
await page.waitForFunction(() => document.body.dataset.ready === "1", { timeout: 60000 });
await page.pdf({
  path: pdf,
  format: "A4",
  printBackground: true,
  displayHeaderFooter: true,
  headerTemplate: `<div style="font-size:8px;width:100%;text-align:center;color:#667;font-family:'Microsoft YaHei',sans-serif;padding-top:6px;">洛克王国智能助手 · 新手复现指南</div>`,
  footerTemplate: `<div style="font-size:8px;width:100%;text-align:center;color:#667;font-family:'Microsoft YaHei',sans-serif;padding-bottom:6px;"><span class="pageNumber"></span> / <span class="totalPages"></span></div>`,
  margin: { top: "16mm", bottom: "16mm", left: "12mm", right: "12mm" },
});
await browser.close();
