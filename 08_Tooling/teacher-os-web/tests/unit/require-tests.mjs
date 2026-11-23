// Guard for `npm run test:unit`: Node's test runner exits 0 when a glob matches
// no files and counts an empty file as one passing test, so a bare `node --test`
// can be green with no real tests. This reads the TAP stream on stdin, echoes
// it, and fails unless the run reported zero failures and at least --min tests.
import { createInterface } from "node:readline";

const minIndex = process.argv.indexOf("--min");
const min = minIndex > 0 ? Number(process.argv[minIndex + 1]) : NaN;
if (!Number.isInteger(min) || min < 1) {
  console.error("require-tests: pass --min <positive integer>");
  process.exit(2);
}

const totals = {};
for await (const line of createInterface({ input: process.stdin })) {
  console.log(line);
  const match = /^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$/.exec(line);
  if (match) totals[match[1]] = Number(match[2]);
}

const problems = [];
if (totals.tests === undefined) problems.push("no TAP summary (runner crashed or produced no output)");
if ((totals.fail ?? 0) > 0 || (totals.cancelled ?? 0) > 0) problems.push(`${totals.fail ?? 0} failed, ${totals.cancelled ?? 0} cancelled`);
if ((totals.pass ?? 0) < min) problems.push(`only ${totals.pass ?? 0} tests passed; at least ${min} are required`);
if ((totals.skipped ?? 0) > 0 || (totals.todo ?? 0) > 0) problems.push("skipped or todo tests are not allowed in the unit suite");
if (problems.length) {
  console.error(`require-tests: FAIL - ${problems.join("; ")}`);
  process.exit(1);
}
console.error(`require-tests: ${totals.pass} passed (minimum ${min})`);
