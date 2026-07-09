# ChatGPT Knowledge Base Setup - Pruning Guide

**This document tells you exactly which files to keep and which to remove from your Custom GPT Knowledge Base.**

---

## Problem We're Solving

Your ChatGPT Custom GPT was failing silently because:

1. **Too many files** (70+ markdown files)
2. **File references** ChatGPT can't resolve ("See `file.md`")
3. **Large knowledge base** caused retrieval to break (>100 files threshold)
4. **Circular references** confused ChatGPT's understanding

**Solution:** Keep only 20-25 essential files, all self-contained and flattened.

---

## Step 1: Remove These Files From Knowledge Base

**🗑️ DELETE FROM KNOWLEDGE BASE (but keep in repo):**

### Large Test/Implementation Docs
- ❌ `TESTING-QUICK-START.md` (305 lines - too long)
- ❌ `01_Shared_Standards/python/IMPLEMENTATION-PATHS.md` (340 lines - too long)
- ❌ `03_Templates/prompts/implement-testing-strategy.md` (1000+ lines)
- ❌ `03_Templates/reports/testing-governance-implementation.md` (1000+ lines)

### All 39 Modular Python Standards (Keep repo, remove from GPT)
- ❌ `01_Shared_Standards/python/frameworks/` (all 5 files)
- ❌ `01_Shared_Standards/python/unit-testing/` (all 5 files)
- ❌ `01_Shared_Standards/python/integration-testing/` (all 6 files)
- ❌ `01_Shared_Standards/python/coverage/` (all 4 files)
- ❌ `01_Shared_Standards/python/environments/` (all 6 files)
- ❌ `01_Shared_Standards/python/ci-cd/` (all 5 files)
- ❌ `01_Shared_Standards/python/INDEX.md`
- ❌ `01_Shared_Standards/python/README.md`

### Large Original Standards
- ❌ `01_Shared_Standards/python/testing-standard.md` (9.5 KB - summarize instead)
- ❌ `01_Shared_Standards/python/unit-testing-standard.md` (7.8 KB)
- ❌ `01_Shared_Standards/python/integration-testing-standard.md` (11.4 KB)
- ❌ `01_Shared_Standards/python/test-environment-setup.md` (10.9 KB)

### Examples & Archive
- ❌ `05_Examples/` folder (all files - reference, not for GPT)
- ❌ `06_Archive/` folder (all files - historical only)

### Templates (Keep minimal)
- ❌ `03_Templates/python-project-template/test_conftest.py`
- ❌ `03_Templates/python-project-template/test_unit_template.py`
- ❌ `03_Templates/python-project-template/test_integration_template.py`

**Total to remove: ~50 files**

---

## Step 2: Keep These Files in Knowledge Base

**✅ KEEP IN KNOWLEDGE BASE (upload these):**

### Core Governance (MUST HAVE)
- ✅ `00_Governance/write-authorization-policy.md` (Core rule: read-only default)
- ✅ `00_Governance/ownership-and-source-of-truth.md` (Where authority lives)

### Global Engineering Standards (MUST HAVE)
- ✅ `01_Shared_Standards/global-engineering/testing-standard.md`
- ✅ `01_Shared_Standards/global-engineering/code-quality-standard.md`
- ✅ `01_Shared_Standards/global-engineering/release-standard.md`
- ✅ `01_Shared_Standards/global-engineering/bug-learning-process.md`

### Python Standards (COMPACT - Keep ONE summary)
- ✅ `01_Shared_Standards/python/testing-standard.md` (ONE file, covers everything)

### Agent Overlays (FLATTENED - All 9)
- ✅ `02_Agent_Overlays/CHATGPT/python-development-overlay.md` (Self-contained)
- ✅ `02_Agent_Overlays/CHATGPT/google-workspace-automation-engineer.md` (Self-contained)
- ✅ `02_Agent_Overlays/CHATGPT/dashboard-builder-overlay.md` (Self-contained)
- ✅ `02_Agent_Overlays/CHATGPT/qa-test-agent.md` (Self-contained)
- ✅ `02_Agent_Overlays/CHATGPT/apps-script-sync-test-overlay.md` (Self-contained)
- ✅ `02_Agent_Overlays/CHATGPT/instructional-materials-coach.md` (Self-contained)
- ✅ `02_Agent_Overlays/CHATGPT/modeling-dashboard-governance-agent.md` (Self-contained)
- ✅ `02_Agent_Overlays/CHATGPT/workspace-implementation-overlay.md` (Self-contained)
- ✅ `02_Agent_Overlays/CHATGPT/integration-manager.md` (Self-contained)

### Other Standards (Minimal)
- ✅ `01_Shared_Standards/google-workspace/write-safety-standard.md`
- ✅ `01_Shared_Standards/notion/write-safety-standard.md`

### Templates (Minimal)
- ✅ `03_Templates/README.md` (Quick reference)
- ✅ `03_Templates/prompts/quick-start-testing-setup.md` (Concise setup guide)

### Registry (For reference)
- ✅ `04_Registry/agent-inheritance-registry.md` (Shows agent roles)
- ✅ `04_Registry/ownership-matrix.md` (Shows who owns what)

**Total to keep: ~20-22 files**

---

## Step 3: Upload Order

**Do this in your Custom GPT Knowledge Base:**

1. **Clear everything** - Remove all files from knowledge base
2. **Upload Core** - Start with governance and standards (5 files)
3. **Upload Overlays** - Add all 9 flattened overlays (9 files)
4. **Upload Optional** - Add templates and registry if needed (5 files)
5. **Test** - Send a message, verify you get response

**Example upload sequence:**
```
1. write-authorization-policy.md
2. ownership-and-source-of-truth.md
3. 01_Shared_Standards/global-engineering/ (all 4 files)
4. 01_Shared_Standards/python/testing-standard.md (ONE file)
5. 02_Agent_Overlays/CHATGPT/ (all 9 flattened overlays)
6. 01_Shared_Standards/google-workspace/write-safety-standard.md
7. 01_Shared_Standards/notion/write-safety-standard.md
8. 03_Templates/README.md
9. 04_Registry/agent-inheritance-registry.md
10. Test
```

---

## File Counts

| Category | Remove | Keep | Notes |
|---|---|---|---|
| Python Standards | 39 modular | 1 summary | Collapse 39 into 1 |
| Large Guides | 4 files | 0 | Archive (>10KB each) |
| Governance | 0 | 2 files | CRITICAL - keep both |
| Global Standards | 0 | 4 files | CRITICAL - all needed |
| Overlays | 0 | 9 files | NEW flattened versions |
| Templates | 5 files | 2 files | Keep only README and quick-start |
| Registry | 0 | 2 files | Reference files |
| Examples/Archive | ~10 files | 0 | Repo reference only |
| **TOTAL** | **~62 files** | **~20 files** | **Reduction: 68%** |

---

## Verification Checklist

After uploading, verify:

- [ ] All 9 CHATGPT overlays uploaded
- [ ] Core governance files present
- [ ] No files with "See `file.md`" references
- [ ] No 39 modular Python docs in knowledge base
- [ ] No TESTING-QUICK-START or IMPLEMENTATION-PATHS
- [ ] Total files: 20-25 max
- [ ] No duplicate files

---

## Testing the Reduced Knowledge Base

After pruning, test with these messages:

### Test 1: Quick Role Identification
**Message:** "I need to write a Python function. Can you help?"
**Expected:** Agent immediately identifies Python Developer role
**Not Expected:** Silence, "loading", or delayed response

### Test 2: Workspace Task
**Message:** "I want to automate my Google Sheets"
**Expected:** Agent asks clarifying questions, explains design
**Not Expected:** Silent or generic response

### Test 3: Blocked Write
**Message:** "Update my Notion database with this"
**Expected:** Agent stops and asks for authorization
**Not Expected:** Proceeds without permission or silent

### Test 4: Get Final Report
**Message:** "Refactor this Python code"
**Expected:** Provides complete final report with files changed, tests run, coverage
**Not Expected:** Missing report sections or incomplete

---

## If Agent Still Silent After Pruning

**Diagnostic steps:**

1. **Test with simple message:** "What's your role?"
   - Should get instant response
   - If not: problem is still in instructions or knowledge base

2. **Check instructions:** Paste MASTER-INSTRUCTIONS.md content
   - If not in system instructions: do that first
   - If already there: might be knowledge base bloat

3. **Remove more files:** Start with ONLY core governance + 1 overlay
   - Upload just 5 files total
   - Test
   - Add more gradually

4. **Check file format:** Make sure `.md` files are valid markdown
   - No binary/corrupted files
   - UTF-8 encoding
   - Proper markdown syntax

5. **Create fresh conversation:** Start new chat to bypass cache issues

---

## Long-Term Maintenance

Keep knowledge base lean:

- **Max files:** 30 (golden zone is 15-25)
- **Max per file:** 15 KB (split larger files)
- **No references:** Each file is self-contained
- **Annual pruning:** Review and remove unused files

---

## Files Kept vs. Removed Breakdown

```
Knowledge Base Optimization

Before (Broken):
├─ Governance: 4 files
├─ Standards: 12+ files  
├─ Python Standards: 39 files ← BLOATED
├─ Overlays: 10 files (broken refs) ← BROKEN
├─ Templates: 8 files
├─ Examples: 5 files
└─ TOTAL: 78 files ❌ Too many, retrieval fails

After (Fixed):
├─ Governance: 2 files ✅ Core only
├─ Standards: 6 files ✅ Condensed
├─ Python Standards: 1 file ✅ Summary only
├─ Overlays: 9 files ✅ Flattened, self-contained
├─ Templates: 2 files ✅ Essential only
├─ Registry: 2 files ✅ Reference
└─ TOTAL: 22 files ✅ Lightweight, fast
```

---

## Done!

Once you:
1. ✅ Delete 60 files from knowledge base
2. ✅ Upload 20 files from list above
3. ✅ Paste MASTER-INSTRUCTIONS.md into Instructions
4. ✅ Test with sample messages

Your agents will start responding again.

**Next step:** See `MASTER-INSTRUCTIONS.md` for setup.
