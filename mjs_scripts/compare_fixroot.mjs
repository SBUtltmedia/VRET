import puppeteer from 'puppeteer';
import { createServer } from 'http';
import { readFile } from 'fs/promises';
import { extname, join, dirname } from 'path';
import { fileURLToPath } from 'url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const MIME = {
  '.html':'text/html', '.js':'text/javascript', '.mjs':'text/javascript',
  '.json':'application/json', '.vrm':'model/gltf-binary',
  '.vrma':'model/gltf-binary', '.glb':'model/gltf-binary',
  '.png':'image/png', '.jpg':'image/jpeg',
};

async function serve(port) {
  return new Promise(resolve => {
    const srv = createServer(async (req, res) => {
      const url = req.url.split('?')[0].split('#')[0];
      const path = join(ROOT, decodeURIComponent(url === '/' ? '/plays/test_basic.html' : url));
      try {
        const data = await readFile(path);
        res.writeHead(200, { 'Content-Type': MIME[extname(path)] ?? 'application/octet-stream' });
        res.end(data);
      } catch { res.writeHead(404); res.end('Not found'); }
    }).listen(port, () => resolve(srv));
  });
}

async function runTest(port, fixRoot, pool, seed) {
  const url = `http://localhost:${port}/plays/test_basic.html?test=true&fixroot=${fixRoot}&pair=${pool}&seed=${seed}`;
  const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox', '--use-gl=angle'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720 });
  
  page.on('console', msg => {
    if (msg.text().startsWith('[test]') || msg.type() === 'error' || msg.type() === 'warning')
      console.log(`  [${fixRoot}] ${msg.text().substring(0, 200)}`);
  });

  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForFunction(
    () => document.body.getAttribute('data-status') === 'complete' || document.body.getAttribute('data-status') === 'error',
    { timeout: 120000 }
  );
  const result = await page.evaluate(() => window.__TEST_DATA);
  await browser.close();
  return result;
}

async function main() {
  // Use gesture-only clips to isolate drift from walking
  const pool = '02_01,111_37';  // gesture→gesture pair
  const seed = '42';
  
  let port = 3510;
  const server = await serve(port);
  
  console.log(`Testing fixRootPosition=false vs true with pool=${pool}`);
  
  const rFalse = await runTest(port, 'false', pool, seed);
  console.log(`\nfixRoot=false results:`);
  console.log(`  totalDriftXY: ${rFalse?.drift?.totalDriftXY ?? 'N/A'}m`);
  console.log(`  endPos: (${rFalse?.endHipsPos?.x ?? '?'}, ${rFalse?.endHipsPos?.y ?? '?'}, ${rFalse?.endHipsPos?.z ?? '?'})`);
  console.log(`  clipDrift: ${JSON.stringify(rFalse?.drift?.clipDriftSummary ?? {})}`);
  
  const rTrue = await runTest(port, 'true', pool, seed);
  console.log(`\nfixRoot=true results:`);
  console.log(`  totalDriftXY: ${rTrue?.drift?.totalDriftXY ?? 'N/A'}m`);
  console.log(`  endPos: (${rTrue?.endHipsPos?.x ?? '?'}, ${rTrue?.endHipsPos?.y ?? '?'}, ${rTrue?.endHipsPos?.z ?? '?'})`);
  console.log(`  clipDrift: ${JSON.stringify(rTrue?.drift?.clipDriftSummary ?? {})}`);
  
  // Comparison
  if (rFalse && rTrue) {
    const driftDiff = ((rTrue.drift?.totalDriftXY ?? 0) - (rFalse.drift?.totalDriftXY ?? 0)) * 100;
    console.log(`\nDrift difference (true - false): ${driftDiff.toFixed(2)}cm`);
    console.log(`fixRoot=true drift is ${driftDiff > 1 ? 'MORE' : driftDiff < -1 ? 'LESS' : 'SIMILAR to'} fixRoot=false`);
    console.log(`Conclusion: fixRootPosition is ${Math.abs(driftDiff) > 2 ? 'LIKELY THE CAUSE' : 'NOT the cause'} of the slide`);
  }
  
  server.close();
  process.exit(0);
}

main();
