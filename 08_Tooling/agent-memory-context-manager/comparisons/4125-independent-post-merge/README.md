# CKR independent post-merge comparison, #4125

- Baseline: first parent `09136c9cd0e7d46cd20777766105fded8f29210a`.
- Treatment: merged main `41c5e5b039bcf8d5eb23b34b8f76c457c8e60055`, with PR parent `68662b2b515aa054b3aa71b921084c4b07fcc13c`. The 30 local source files on each side were Git-blob-verified against their pinned revision.
- An independent AI reviewer saw only frozen task prompts and catalog panels. It did not see code or outputs. It marked 14 positive cases and 8 abstentions before execution. The SHA-256 is in gold.sha256. The selector saw no lesson IDs or labels in the requests.
- The same input was tested in both row orders on each side; each revision produced byte-identical output in both orders (88 total executions). No live Notion read or external write ran for this test.

| Panel | Pre-merge correct / wrong / miss / abstain | Merged correct / wrong / miss / abstain |
| --- | --- | --- |
| 14 archived real-task cases over 35 archived catalog rows | 1 / 0 / 10 / 3 | 1 / 0 / 10 / 3 |
| 8 synthetic controlled cases | 0 / 0 / 3 / 5 | 1 / 0 / 2 / 5 |

Merged CKR picked the post-write Writer guidance and rejected readback before the write, reversed ordering, and unrelated formatting. Neither revision selected the two semantically applicable REST positives under Governance metadata. A separate diagnostic rerun changed only the four REST panels' Area from Governance to Testing; merged CKR then selected both positives and rejected both opposite-advice controls, while pre-merge CKR selected none. This shows sensitivity to a structured category requirement; it does not change the blind score or establish a live catalog metadata defect.

Manual review on an applicable case is a miss, not a wrong pick or a safety violation. The 35-row archived subset is not the current catalog. The independent reviewer is AI, not human. No claim is made about live accuracy or the entire population. The separate [hosted post-merge aggregate](https://github.com/Blummer92/agent-os/actions/runs/45840166009/job/139979414143) passed.

## Reproduction

To reproduce the locked result, stage the listed source blobs for the two revisions in sibling directory `postmerge-4125-ckr/{main,pr}`, then run `QA_PYTHON=/path/to/python bash replay.sh`. The script verifies frozen inputs and gold before execution and requires exact equality when reversing row order. `comparison.tsv` records judgments and selections. The area probe files are deliberately outside the scored results.
