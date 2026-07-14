function runHandoffServiceTests() {
  const tests = [
    testHandoffNamesUnitAlignmentDestination_,
    testHandoffCountsReadyUnitAlignmentRows_,
    testHandoffBlocksMissingFileId_,
    testHandoffFlagsOptionalExtensionDrift_
  ];
  const results = tests.map(function(testFn) {
    try {
      testFn();
      return { name: testFn.name, status: 'passed' };
    } catch (error) {
      return { name: testFn.name, status: 'failed', message: error.message };
    }
  });
  const failures = results.filter(function(result) { return result.status === 'failed'; });
  if (failures.length) {
    throw new Error('HandoffService tests failed: ' + JSON.stringify(results));
  }
  Logger.log(JSON.stringify(results, null, 2));
  return results;
}

function testHandoffNamesUnitAlignmentDestination_() {
  const text = HandoffService.buildHandoffText([buildUnitAlignmentHandoffFixture_()], [], { totalRecords: 1 });
  assertTextIncludes_(text, 'Unit Alignment Handoff Preview', 'handoff should be retitled');
  assertTextIncludes_(text, 'Destination: Unit Alignment Coach', 'handoff should name Unit Alignment Coach');
  assertTextIncludes_(text, 'dryRunUnitAlignmentCoachBatch', 'handoff should point to dry-run gate');
}

function testHandoffCountsReadyUnitAlignmentRows_() {
  const summary = HandoffService.__test__.buildUnitAlignmentHandoff([buildUnitAlignmentHandoffFixture_()]);
  assertEquals_(1, summary.candidate_count, 'one Unit Alignment candidate should be counted');
  assertEquals_(1, summary.ready_count, 'clean candidate should be ready');
  assertEquals_(0, summary.blocked_count, 'clean candidate should not block');
}

function testHandoffBlocksMissingFileId_() {
  const summary = HandoffService.__test__.buildUnitAlignmentHandoff([
    buildUnitAlignmentHandoffFixture_({ file_id: '' })
  ]);
  assertEquals_(1, summary.blocked_count, 'missing file_id should block');
  assertEquals_(1, summary.missing_file_id_count, 'missing file_id should be counted');
}

function testHandoffFlagsOptionalExtensionDrift_() {
  const summary = HandoffService.__test__.buildUnitAlignmentHandoff([
    buildUnitAlignmentHandoffFixture_({
      daily_must_have_evidence: 'Required comic page and 3-panel Hero Moment',
      deliverable_scope: 'core required'
    })
  ]);
  assertEquals_(1, summary.blocked_count, 'optional extension drift should block');
  assertEquals_(1, summary.optional_extension_drift_count, 'optional extension drift should be counted');
}

function buildUnitAlignmentHandoffFixture_(overrides) {
  return {
    rowNumber: 2,
    fileId: overrides && Object.prototype.hasOwnProperty.call(overrides, 'file_id') ? overrides.file_id : 'file-2',
    fileName: 'AI Superhero Unit Alignment',
    rawData: Object.assign({
      rowNumber: 2,
      file_id: 'file-2',
      file_name: 'AI Superhero Unit Alignment',
      unit_name: 'AI Superhero',
      alignment_status: 'Final',
      unit_throughline: 'AI-generated characters communicate identity through intentional visual choices.',
      daily_must_have_evidence: '2 visual choices + meanings',
      teacher_anchor: 'AI generates images, but designers create meaning.',
      learning_target: 'I can use visible choices to explain identity.',
      checkpoint_evidence: 'daily visible evidence checkpoint',
      source_of_truth_priority: 'Unit throughline before activities',
      notes: 'Teacher says: I am looking for visible evidence before judging the image.'
    }, overrides || {})
  };
}

function assertEquals_(expected, actual, message) {
  if (expected !== actual) {
    throw new Error(message + '. Expected ' + expected + ', got ' + actual);
  }
}

function assertTextIncludes_(text, expected, message) {
  if (String(text).indexOf(expected) === -1) {
    throw new Error(message + '. Expected text to include ' + expected);
  }
}
