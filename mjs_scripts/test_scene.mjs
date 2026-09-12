import puppeteer from 'puppeteer';
import { createServer } from 'http';
import { readFile } from 'fs/promises';
import { extname, join, dirname } from 'path';
import { fileURLToPath } from 'url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 3501;
const MIME = {
  '.html':'text/html', '.js':'text/javascript', '.mjs':'text/javascript',
  '.json':'application/json', '.vrm':'model/gltf-binary',
  '.vrma':'model/gltf-binary', '.glb':'model/gltf-binary',
  '.png':'image/png', '.jpg':'image/jpeg',
};

function serve() {
  return new Promise(resolve => {
    const srv = createServer(async (req, res) => {
      const url = req.url.split('?')[0].split('#')[0];
      const path = join(ROOT, decodeURIComponent(url === '/' ? '/plays/scene.html' : url));
      try {
        const data = await readFile(path);
        res.writeHead(200, { 'Content-Type': MIME[extname(path)] ?? 'application/octet-stream' });
        res.end(data);
      } catch { res.writeHead(404); res.end('Not found'); }
    }).listen(PORT, () => { console.log(`[test] Server on :${PORT}`); resolve(srv); });
  });
}

async function main() {
  const server = await serve();
  const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox', '--use-gl=angle'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720 });

  page.on('console', msg => console.log(`[${msg.type()}] ${msg.text()}`));
  page.on('pageerror', err => console.log(`[PAGE_ERROR] ${err.message}`));

  const url = `http://localhost:${PORT}/plays/scene.html?test=true`;

  console.log(`[test] Loading ${url}`);
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    console.log('[test] Waiting for scene completion...');
    await page.waitForFunction(
      () => document.body.getAttribute('data-status') === 'complete',
      { timeout: 300000 }
    );

    const testData = await page.evaluate(() => window.__TEST_DATA);
    console.log('[test] Result:', JSON.stringify(testData, null, 2));

    const pass = testData?.maxSnapDeg < 15;
    console.log(`[test] ${pass ? 'PASS' : 'FAIL'} — max snap ${testData?.maxSnapDeg?.toFixed(2) ?? 'N/A'}° (threshold 15°)`);
  } catch (err) {
    console.log(`[test] TIMEOUT or ERROR: ${err.message}`);
    try {
      await page.screenshot({ path: 'test_scene_fail.png' });
      console.log('[test] Screenshot saved to test_scene_fail.png');
    } catch {}
  }

  await browser.close();
  server.close();
  process.exit(0);
}

main();
