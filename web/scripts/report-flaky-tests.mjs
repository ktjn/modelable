import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export function collectFlakyTests(report) {
  const flaky = [];
  const walk = (suite, titlePath) => {
    for (const spec of suite.specs ?? []) {
      const specTitlePath = [...titlePath, spec.title];
      for (const test of spec.tests) {
        if (test.status === 'flaky') {
          flaky.push({
            title: specTitlePath.join(' > '),
            file: spec.file,
            line: spec.line,
            project: test.projectName,
            attempts: test.results.length,
          });
        }
      }
    }
    for (const child of suite.suites ?? []) {
      walk(child, [...titlePath, child.title]);
    }
  };
  for (const suite of report.suites ?? []) {
    walk(suite, []);
  }
  return flaky;
}

export async function main(resultsPath) {
  let raw;
  try {
    raw = await readFile(resultsPath, 'utf-8');
  } catch {
    // No report to inspect (e.g. the run was interrupted before the JSON
    // reporter wrote output) -- nothing to report, not a failure.
    return 0;
  }
  const report = JSON.parse(raw);
  const flaky = collectFlakyTests(report);
  if (flaky.length === 0) {
    console.log('No flaky E2E tests this run.');
    return 0;
  }
  console.log(`${flaky.length} flaky E2E test(s) passed only after retry:`);
  for (const test of flaky) {
    const location = `${test.file}:${test.line}`;
    console.log(`  - [${test.project}] ${test.title} (${location}, ${test.attempts} attempts)`);
    // GitHub Actions warning annotation -- visible in the run summary
    // without failing the job, since the test did eventually pass.
    console.log(`::warning file=${test.file},line=${test.line}::Flaky E2E test: ${test.title}`);
  }
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main(process.argv[2] ?? 'output/playwright/results.json');
}
