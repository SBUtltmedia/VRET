import puppeteer from 'puppeteer';
import { createServer } from 'http';
import { readFile } from 'fs/promises';
import { execSync } from 'child_process';
import { extname, join, dirname } from 'path';
import { fileURLToPath } from 'url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 3502;
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
      const path = join(ROOT, decodeURIComponent(url === '/' ? '/plays/test_basic.html' : url));
      try {
        const data = await readFile(path);
        res.writeHead(200, { 'Content-Type': MIME[extname(path)] ?? 'application/octet-stream' });
        res.end(data);
      } catch { res.writeHead(404); res.end('Not found'); }
    }).listen(PORT, () => { console.log(`[test] Server on :${PORT}`); resolve(srv); });
  });
}

async function main() {
  // Parse command-line pair argument: --pair=A,B or default
  const pairArg = process.argv.find(a => a.startsWith('--pair='));
  const defaultPair = pairArg ? pairArg.split('=')[1] : '02_01,111_37';
  const [pickA, pickB] = defaultPair.split(',').map(s => s.trim().replace('.vrma','') + '.vrma');

  // Generate transition VRMA
  const txName = `tx_${pickA.replace('.vrma','')}_to_${pickB.replace('.vrma','')}.vrma`;
  const txPath = join(ROOT, 'vrma', txName);
  const genCmd = `python "${join(ROOT, 'python_scripts', 'generate_transition_vrma.py')}" "${join(ROOT, 'vrma', pickA)}" "${join(ROOT, 'vrma', pickB)}" -o "${txPath}" --threshold 15 --fps 60`;

  console.log(`[test] Generating transition: ${pickA} -> ${pickB}`);
  console.log(`[test] ${genCmd}`);
  try {
    const out = execSync(genCmd, { timeout: 60000 });
    console.log(out.toString());
  } catch (err) {
    console.error(`[test] TRANSITION GENERATION FAILED: ${err.message}`);
    process.exit(1);
  }

  const server = await serve();
  const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox', '--use-gl=angle'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720 });

  page.on('console', msg => {
    if (msg.text().startsWith('[test]') || msg.text().startsWith('[snap]')) console.log(msg.text());
    else if (msg.type() === 'error' || msg.type() === 'warning') console.log(`[${msg.type()}] ${msg.text()}`);
  });
  page.on('pageerror', err => console.log(`[PAGE_ERROR] ${err.message}`));

  const url = `http://localhost:${PORT}/plays/test_basic.html?test=true&pair=${pickA},${pickB}&transition=${txName}`;

  console.log(`[test] Loading ${url}`);
  let pass = false;
  let result = null;
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    console.log('[test] Waiting for scene completion...');
    await page.waitForFunction(
      () => document.body.getAttribute('data-status') === 'complete' || document.body.getAttribute('data-status') === 'error',
      { timeout: 300000 }
    );

    result = await page.evaluate(() => window.__TEST_DATA);
    console.log('[test] Result:', JSON.stringify(result, null, 2));

    const failures = [];

    if (!result?.completed) failures.push('!completed');
    if (!result?.retargetSuccess) failures.push('retarget failed');
    if ((result?.maxSnapDeg ?? 999) >= 15) failures.push(`rotation snap ${result.maxSnapDeg}° >= 15°`);
    if ((result?.maxPosSnap ?? 999) >= 0.05) failures.push(`position snap ${result.maxPosSnap}m >= 0.05m`);
    if ((result?.totalFramesAdvanced ?? 0) === 0) failures.push('no animation frames advanced');
    if (result?.eventsCompleted !== '3 of 3') failures.push(`events ${result.eventsCompleted} !== 3 of 3`);

    pass = failures.length === 0;
    if (pass) {
      console.log(`[test] PASS — max snap ${result.maxSnapDeg}°, max pos snap ${result.maxPosSnap}m, frames ${result.totalFramesAdvanced}`);
    } else {
      console.log(`[test] FAIL — ${failures.join(', ')}`);
    }
  } catch (err) {
    console.log(`[test] TIMEOUT or ERROR: ${err.message}`);
    try {
      await page.screenshot({ path: 'test_basic_fail.png' });
      console.log('[test] Screenshot saved to test_basic_fail.png');
    } catch {}
  }

  // Cleanup transition VRMA
  try {
    const { unlinkSync } = await import('fs');
    unlinkSync(txPath);
  } catch {}

  await browser.close();
  server.close();
  process.exit(pass ? 0 : 1);
}

main();
