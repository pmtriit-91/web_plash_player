# Web Flash Player Pro — Documentation Map

This document establishes the canonical placement and authority matrix for Web Flash Player Pro under Universal Agent OS V9.1.0.

## Project Authority Matrix

| Concern | Canonical Authority | Update Trigger | Forbidden Duplication |
| --- | --- | --- | --- |
| Mission & Constitutional Truth | `.agents/project/genesis.json` | Owner-confirmed constitutional change | Unsynced claims in Markdown |
| Roadmap & Milestones | `.agents/project/roadmap.md` | Milestone completion or phase transition | Unverified task lists |
| Task History & Ledger | `.agents/project/task-ledger.md` | Task completion, mutation, or handoff | Fleeting chat summaries |
| Architecture & Topology | `.agents/project/architecture-map.md` | Network bridge, proxy, or WASM changes | Stale design notes |
| Architecture Decisions (ADR) | `.agents/project/known-decisions.md` | Critical architectural decision taken | Ad-hoc code comments |
| Project Memory Projection | `.agents/skills/project-memory/SKILL.md` | Context Memory refresh | Manual projection edits |

## Directory Roles

- `.agents/project/`: Application-owned durable governance, constitution, roadmap, and decision records.
- `src/`: Client-side UI, Ruffle WebAssembly integration, controls, preset management, and DOM events.
- `server/`: Node.js Universal Bridge, Asset Reverse Proxy, Dynamic XML Rewriter, and WebSocket-to-TCP Gateway.
- `public/`: Static assets, Vietnamese Unicode TrueType fonts (`Arial.ttf`, `Tahoma.ttf`), DDTank templates.
