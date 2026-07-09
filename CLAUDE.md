# Agent OS — CLAUDE.md

**Version:** 0.1.1-draft  
**Last Updated:** 2026-07-07  
**Repository:** `blummer92/agent-os`  
**Branch:** `claude/claude-md-docs-dnzy18`

---

## Current Operating Mode

Agent OS is in Advisory Mode during pilot review.

Use `00_Governance/agent-os-advisory-mode.md` as the default behavior for day-to-day work.

Agent OS should not block read-only, local-only, planning, drafting, QA notes, summaries, code review, local specs, or local documentation tasks.

Strict approval gates still apply to external writes, production data, governed fields, source-of-truth records, sharing/permissions, sensitive student/private data, and irreversible actions.

---

## Overview

**Agent OS** is a modular, standards-first knowledge base for engineering agents. It defines governance rules, shared standards, agent-specific overlays, registry maps, reusable templates, and examples—all organized to provide clear source-of-truth documentation for AI assistants working on coding and automation tasks.

This repository is a **draft canonical source** for engineering-agent standards. It does not yet govern live agent behavior but serves as a reference library for review, adoption, and future integration into live systems.

---

## Repository Structure

Agent OS is organized into eight main directories, each with a specific purpose:

### `00_Governance/`
Foundation-level rules that apply to all agents before any role-specific overlay.

**Key files:**
- `ownership-and-source-of-truth.md` — Where policy lives; no duplication across modules.
- `write-authorization-policy.md` — Write defaults to read-only; explicit approval required.
- `agent-os-advisory-mode.md` — Pilot-review mode for low-risk day-to-day work.
- `engineering-standards-framework.md` — Core coding principles: modular design, testing, reporting.
- `memory-rules.md` — What agents should memorize vs. reference from files.
- `standards-change-control.md` — How to update standards safely.
- `agent-creation-policy.md` — Rule against redundant agents; points to `04_Registry/agent-inheritance-registry.md` for the canonical agent list.

**Convention:** Governance rules are inherited by all other modules. They are not repeated elsewhere.

### `01_Shared_Standards/`
Domain-specific standards inherited by all agents working in that domain.

**Organization by domain:**
- `global-engineering/` — Applies to every coding agent (read-only default, testing, release, bug learning)
- `python/` — Python-specific module structure, testing, packaging
