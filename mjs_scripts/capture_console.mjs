import puppeteer from 'puppeteer';

const url = process.argv[2];
const timeoutArg = process.argv.find(a => a.startsWith('--timeout='));
const WAIT_MS = timeoutArg ? parseInt(timeoutArg.split('=')[1], 10) : 8000;
if (!url || url.startsWith('--')) {
  console.error('Usage: node capture_console.mjs <url> [--timeout=15000]');
  process.exit(1);
}

let hasError = false;

function emit(type, args) {
  process.stdout.write(`[${type}] ${args.join(' ')}\n`);
}

async function main() {
  const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox', '--use-gl=angle'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720 });

  page.on('console', msg => {
    emit(msg.type().toUpperCase(), [msg.text()]);
  });

  page.on('pageerror', err => {
    hasError = true;
    emit('PAGE_ERROR', [err.message]);
  });

  page.on('requestfailed', req => {
    const f = req.failure();
    if (f && f.errorText !== 'net::ERR_ABORTED') {
      hasError = true;
      emit('NET_FAIL', [`${req.url()} — ${f.errorText}`]);
    }
  });

  page.on('response', response => {
    const status = response.status();
    if (status >= 400) {
      hasError = true;
      emit('HTTP_ERR', [`${status} ${response.url()}`]);
    }
  });

  emit('INFO', [`Opening ${url}`]);
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
    emit('WAIT', [`Waiting ${(WAIT_MS/1000).toFixed(0)}s for full sequence...`]);
    await new Promise(r => setTimeout(r, WAIT_MS));
    await page.screenshot({ path: 'capture_output.png', fullPage: false });
    emit('SCREENSHOT', ['Saved to capture_output.png']);
  } catch (err) {
    hasError = true;
    emit('NAV_FAIL', [err.message]);
  }

  await browser.close();
  process.exit(hasError ? 1 : 0);
}

main();
