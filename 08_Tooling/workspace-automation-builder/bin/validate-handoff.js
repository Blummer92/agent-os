#!/usr/bin/env node
const { validateFile } = require('../lib/validate-handoff');

function main(argv) {
  const filePath = argv[2];
  if (!filePath) {
    console.error('Usage: node 08_Tooling/workspace-automation-builder/bin/validate-handoff.js <handoff-or-receipt.json>');
    return 2;
  }

  try {
    validateFile(filePath);
    console.log('Workspace Automation Builder validation passed.');
    return 0;
  } catch (error) {
    console.error('Workspace Automation Builder validation failed: ' + error.message);
    return 1;
  }
}

if (require.main === module) {
  process.exit(main(process.argv));
}

module.exports = { main };
