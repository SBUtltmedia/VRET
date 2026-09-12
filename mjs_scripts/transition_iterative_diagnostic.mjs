/**
 * transition_iterative_diagnostic.mjs — Iterative transition diagnostic
 *
 * Tests BOTH weight-based crossfade and VRMA-spline transition methods
 * across multiple durations, comparing physical constraint violations.
 *
 * Usage:
 *   node mjs_scripts/transition_iterative_diagnostic.mjs
 */

import puppeteer from 'puppeteer';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCENE_HTML = path.resolve(__dirname, '..', 'plays', 'scene.html');
const SNAP_THRESH = 1.0;
const FINGER_BONE_RE = /thumb|index|middle|ring|little|metacarpal|finger/i;
const OUT_DIR = path.resolve(__dirname, '..', 'reports', 'transition_iter');
fs.mkdirSync(OUT_DIR, { recursive: true });

const results = [];

async function runConfig(label, queryString) {
  const url = `file:///${SCENE_HTML.replace(/\\/g, '/')}?test&snap=${SNAP_THRESH}${queryString}`;
  console.log(`\n  [${label}] ${queryString}`);

  const browser = await puppeteer.launch({
    headless: 'new',
    protocolTimeout: 600000,
    args: ['--no-sandbox', '--disable-web-security', '--use-gl=angle'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720 });
  page.setDefaultTimeout(600000);

  page.on('console', msg => {
    const t = msg.text();
    if (t.includes('[PHYSICAL VIOLATION]') || t.includes('[scene]') || t.includes('[TransitionGenerator]')) {
      fs.appendFileSync(path.join(OUT_DIR, 'logs.txt'), `[${label}] ${t}\n`);
    }
  });

  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await page.waitForFunction(
    () => document.body.getAttribute('data-status') === 'complete',
    { timeout: 600000 }
  );

  const testData = await page.evaluate(() => window.__TEST_DATA);
  await browser.close();
  return testData;
}

function analyzeTestData(testData, label) {
  if (!testData?.completed) return null;

  const violations = (testData.physicalViolations || [])
    .filter(v => !FINGER_BONE_RE.test(v.bone || ''));
  const smooth = testData.transitionSmooth;
  const events = smooth?.events || [];
  
  const snapViolations = violations.filter(v => v.type === 'snap' || !v.type);
  const accelViolations = violations.filter(v => v.type === 'accel_spike');
  const jerkViolations  = violations.filter(v => v.type === 'jerk_spike');
  const curveViolations = violations.filter(v => v.type === 'curvature');
  const slideViolations = violations.filter(v => v.type === 'foot_slide');

  const totalViolations = violations.length;
  const byPhase = testData.violationsByPhase || { fadeIn: 0, steady: 0, fadeOut: 0 };
  const byBone = {};
  for (const v of violations) byBone[v.bone] = (byBone[v.bone] || 0) + 1;
  const boneCount = Object.keys(byBone).length;
  
  const worstSnap = snapViolations.length > 0
    ? Math.max(...snapViolations.map(v => v.angle || 0))
    : 0;
  const worstAccel = accelViolations.length > 0
    ? Math.max(...accelViolations.map(v => v.accel || 0))
    : 0;
  const worstJerk = jerkViolations.length > 0
    ? Math.max(...jerkViolations.map(v => v.jerk || 0))
    : 0;

  let totalFadeRatio = 0, totalFadeOutRatio = 0, totalSnap = 0;
  let ratioCount = 0, snapCount = 0;
  let maxFadeRatio = 0, maxFadeOutRatio = 0, maxSnap = 0;
  let armViolations = 0;

  for (const v of violations) {
    if (v.bone?.includes('UpperArm') || v.bone?.includes('upperArm')) armViolations++;
  }

  for (const ev of events) {
    if (ev.hasGesture) {
      if (ev.fadeToSteadyRatio != null) {
        totalFadeRatio += ev.fadeToSteadyRatio;
        ratioCount++;
        if (ev.fadeToSteadyRatio > maxFadeRatio) maxFadeRatio = ev.fadeToSteadyRatio;
      }
      if (ev.fadeOutToSteadyRatio != null) {
        totalFadeOutRatio += ev.fadeOutToSteadyRatio;
        if (ev.fadeOutToSteadyRatio > maxFadeOutRatio) maxFadeOutRatio = ev.fadeOutToSteadyRatio;
      }
      if (ev.returnSnapMaxDeg != null) {
        totalSnap += ev.returnSnapMaxDeg;
        snapCount++;
        if (ev.returnSnapMaxDeg > maxSnap) maxSnap = ev.returnSnapMaxDeg;
      }
    }
  }

  const passCount = events.filter(e => {
    if (!e.hasGesture) return true;
    return (e.fadeToSteadyRatio ?? 0) <= 3.0
        && (e.fadeOutToSteadyRatio ?? 0) <= 3.0
        && (e.returnSnapMaxDeg ?? 0) <= 3.0;
  }).length;

  const transitionViolations = byPhase.fadeIn + byPhase.fadeOut;
  const pct = totalViolations > 0 ? ((transitionViolations / totalViolations) * 100).toFixed(1) : '0.0';

  return {
    label,
    totalViolations,
    snapCount: snapViolations.length,
    accelCount: accelViolations.length,
    jerkCount: jerkViolations.length,
    curveCount: curveViolations.length,
    slideCount: slideViolations.length,
    violationsByPhase: byPhase,
    transitionViolations,
    steadyViolations: byPhase.steady || 0,
    transitionPct: pct,
    armViolations,
    boneCount,
    worstSnap: +worstSnap.toFixed(2),
    worstAccel: +worstAccel.toFixed(1),
    worstJerk: +worstJerk.toFixed(0),
    avgFadeRatio: ratioCount > 0 ? +(totalFadeRatio / ratioCount).toFixed(2) : null,
    avgFadeOutRatio: ratioCount > 0 ? +(totalFadeOutRatio / ratioCount).toFixed(2) : null,
    avgSnap: snapCount > 0 ? +(totalSnap / snapCount).toFixed(2) : null,
    maxFadeRatio: +maxFadeRatio.toFixed(2),
    maxFadeOutRatio: +maxFadeOutRatio.toFixed(2),
    maxSnap: +maxSnap.toFixed(2),
    passCount,
    totalEvents: events.length,
    violationsByBone: byBone,
    topBones: Object.entries(byBone).sort((a, b) => b[1] - a[1]).slice(0, 5),
    perEvent: events.map((ev, i) => ({
      clip: ev.clip ? ev.clip.split('/').pop() : `event_${i}`,
      hasGesture: ev.hasGesture,
      fadeInMaxDeg: ev.fadeInMaxDegPerFrame,
      steadyMaxDeg: ev.steadyMaxDegPerFrame,
      fadeToSteadyRatio: ev.fadeToSteadyRatio,
      fadeOutMaxDeg: ev.fadeOutMaxDegPerFrame ?? null,
      fadeOutToSteadyRatio: ev.fadeOutToSteadyRatio ?? null,
      returnSnapMaxDeg: ev.returnSnapMaxDeg ?? null,
      angularDistDeg: ev.transitionAngularDistDeg ?? null,
      maxKeyDeltaDeg: ev.maxKeyDeltaDeg ?? null,
      hipFadeIn: ev.hipPosMaxDeltaFadeIn ?? null,
      hipSteady: ev.hipPosMaxDeltaSteady ?? null,
      hipFadeOut: ev.hipPosMaxDeltaFadeOut ?? null,
      hipReturnSnap: ev.hipPosReturnSnap ?? null,
    })),
  };
}

async function main() {
  console.log('╔══════════════════════════════════════════════════════════════════╗');
  console.log('║  Iterative Transition Diagnostic — 4 methods @ multi durations ║');
  console.log('╚══════════════════════════════════════════════════════════════════╝\n');

  // One config per method at same fade duration (0.25s)
  const allConfigs = [
    { label: 'weight-0.25s',  qs: '&transition=weight&fade=0.25' },
    { label: 'vrma-default',  qs: '&transition=vrma&fade=0.25' },
    { label: 'match-0.25s',   qs: '&transition=match&fade=0.25' },
    { label: 'inertial-0.25s',qs: '&transition=inertial&fade=0.25' },
  ];
  const total = allConfigs.length;

  for (let i = 0; i < total; i++) {
    const { label, qs } = allConfigs[i];
    console.log(`[${i + 1}/${total}] ${label}`);
    const testData = await runConfig(label, qs);
    const r = analyzeTestData(testData, label);
    if (r) {
      const vp = r.violationsByPhase;
      console.log(`    violations: ${r.totalViolations} (snaps: ${r.snapCount}, accels: ${r.accelCount}, jerk: ${r.jerkCount}, curve: ${r.curveCount}, slide: ${r.slideCount})`);
      console.log(`    by phase:   fadeIn=${vp.fadeIn} steady=${vp.steady} fadeOut=${vp.fadeOut} (transition=${r.transitionPct}%)`);
      console.log(`    extremes:   worst_snap=${r.worstSnap}°  worst_accel=${r.worstAccel}deg/s²  worst_jerk=${r.worstJerk}deg/s³`);
      console.log(`    fadeRatio:  avg=${r.avgFadeRatio} max=${r.maxFadeRatio}  snap: avg=${r.avgSnap}° max=${r.maxSnap}°`);
      console.log(`    events:     ${r.passCount}/${r.totalEvents} pass`);
      if (r.topBones.length) {
        console.log(`    top bones:  ${r.topBones.map(([n, c]) => `${n}=${c}`).join(', ')}`);
      }
      results.push(r);
    } else {
      console.log(`    SKIP — incomplete`);
    }
  }

  // ── Summary Table ──────────────────────────────────────────────────────
  console.log('\n' + '═'.repeat(140));
  console.log('RESULTS');
  console.log('═'.repeat(140));
  console.log('Method          Snaps  Accels  Jerks  Curves  Slides  Bones  Worst°  WorstAccel  WorstJerk   TxPct   Pass');
  console.log('──────────────  ─────  ──────  ─────  ──────  ──────  ─────  ──────  ──────────  ─────────   ──────  ─────');
  for (const r of results) {
    const txp = r.transitionPct;
    console.log(
      `${String(r.label).padEnd(14)}  ${String(r.snapCount).padStart(5)}  ` +
      `${String(r.accelCount).padStart(6)}  ${String(r.jerkCount).padStart(5)}  ` +
      `${String(r.curveCount).padStart(6)}  ${String(r.slideCount).padStart(6)}  ` +
      `${String(r.boneCount).padStart(5)}  ${String(r.worstSnap).padStart(6)}  ${String(r.worstAccel).padStart(10)}  ` +
      `${String(r.worstJerk).padStart(9)}   ${String(txp).padStart(6)}  ${r.passCount}/${r.totalEvents}`
    );
  }

  // ── Per-event angular distance table (vrma method only) ────────────────
  const vrmaResult = results.find(r => r.label.startsWith('vrma'));
  if (vrmaResult?.perEvent) {
    console.log('\n── Per-event transition metrics (vrma) ──');
    console.log('Ev  Clip      FadeIn°  Steady°  FadeOut°  FRatio  FORatio   Snap°  maxKey°  Pass');
    console.log('──  ────────  ───────  ───────  ────────  ──────  ───────  ──────  ───────  ────');
    for (const ev of vrmaResult.perEvent) {
      const clip = ev.clip.padEnd(8);
      const fi = ev.fadeInMaxDeg != null ? ev.fadeInMaxDeg.toFixed(1).padStart(7) : '    N/A';
      const st = ev.steadyMaxDeg != null ? ev.steadyMaxDeg.toFixed(1).padStart(7) : '    N/A';
      const fo = ev.fadeOutMaxDeg != null ? ev.fadeOutMaxDeg.toFixed(1).padStart(8) : '    N/A';
      const rt = ev.fadeToSteadyRatio != null ? ev.fadeToSteadyRatio.toFixed(1).padStart(6) : '   N/A';
      const or = ev.fadeOutToSteadyRatio != null ? ev.fadeOutToSteadyRatio.toFixed(1).padStart(7) : '    N/A';
      const sn = ev.returnSnapMaxDeg != null ? ev.returnSnapMaxDeg.toFixed(1).padStart(6) : '   N/A';
      const mk = ev.maxKeyDeltaDeg != null ? ev.maxKeyDeltaDeg.toFixed(1).padStart(7) : '    N/A';
      const pass = (ev.fadeToSteadyRatio ?? 0) <= 3 && (ev.fadeOutToSteadyRatio ?? 0) <= 3 && (ev.returnSnapMaxDeg ?? 0) <= 3 ? 'PASS' : 'SNAP';
      console.log(`${String(vrmaResult.perEvent.indexOf(ev)).padStart(2)}  ${clip}  ${fi}  ${st}  ${fo}  ${rt}  ${or}  ${sn}  ${mk}  ${pass}`);
    }
  }

  // ── Compare best of each method ────────────────────────────────────────
  const weightResults = results.filter(r => r.label.startsWith('weight'));
  const vrmaResults = results.filter(r => r.label.startsWith('vrma'));
  const matchResults = results.filter(r => r.label.startsWith('match'));
  const inertialResults = results.filter(r => r.label.startsWith('inertial'));

  function bestOf(arr) {
    return arr.reduce((a, b) => (a.passCount / a.totalEvents) > (b.passCount / b.totalEvents) ? a : b);
  }

  if (weightResults.length) {
    const bestWeight = bestOf(weightResults);
    console.log(`\n── Best weight ── ${bestWeight.label}: ${bestWeight.passCount}/${bestWeight.totalEvents} pass, ${bestWeight.totalViolations} violations, ratio=${bestWeight.avgFadeRatio}`);
  }
  if (vrmaResults.length) {
    const bestVRMA = bestOf(vrmaResults);
    console.log(`── Best vrma   ── ${bestVRMA.label}: ${bestVRMA.passCount}/${bestVRMA.totalEvents} pass, ${bestVRMA.totalViolations} violations, ratio=${bestVRMA.avgFadeRatio}`);
  }
  if (matchResults.length) {
    const bestMatch = bestOf(matchResults);
    console.log(`── Best match  ── ${bestMatch.label}: ${bestMatch.passCount}/${bestMatch.totalEvents} pass, ${bestMatch.totalViolations} violations, ratio=${bestMatch.avgFadeRatio}`);
  }
  if (inertialResults.length) {
    const bestInertial = bestOf(inertialResults);
    console.log(`── Best inertial── ${bestInertial.label}: ${bestInertial.passCount}/${bestInertial.totalEvents} pass, ${bestInertial.totalViolations} violations, ratio=${bestInertial.avgFadeRatio}`);
  }

  // Cross-method comparison
  const allBest = [weightResults, vrmaResults, matchResults, inertialResults]
    .filter(a => a.length)
    .map(a => bestOf(a));
  if (allBest.length >= 2) {
    allBest.sort((a, b) => (b.passCount / b.totalEvents) - (a.passCount / a.totalEvents));
    const top = allBest[0];
    console.log(`\n── Overall best: ${top.label} (${top.passCount}/${top.totalEvents} pass) ──`);
    for (let i = 1; i < allBest.length; i++) {
      const r = allBest[i];
      const vDiff = top.totalViolations - r.totalViolations;
      const pct = r.totalViolations > 0 ? ((vDiff / r.totalViolations) * 100).toFixed(1) : 'N/A';
      console.log(`  ${r.label}: ${vDiff > 0 ? '+' + vDiff : vDiff} violations (${pct}%) vs ${top.label}`);
    }
  }

  // ── Save report ────────────────────────────────────────────────────────
  const reportPath = path.join(OUT_DIR, 'report.json');
  fs.writeFileSync(reportPath, JSON.stringify(results, null, 2));
  console.log(`\n[done] Full report: ${reportPath}`);
}

main().catch(err => {
  console.error('Fatal:', err);
  process.exit(1);
});
