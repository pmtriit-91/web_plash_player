# Web Flash Player Pro — Architectural Decision Records (ADRs)

This document records the foundational architectural decisions, technical trade-offs, and design rationales implemented in Web Flash Player Pro.

---

## ADR-001: Separation of Client WASM Runtime and Network Bridge Daemon
- **Context**: Browsers cannot open raw TCP sockets to arbitrary game servers or bypass strict Cross-Origin Resource Sharing (CORS) headers on remote SWF assets.
- **Decision**: Decouple the system into:
  1. Frontend Web Client (Vite + Ruffle WASM) running on port `5173`.
  2. Universal Network Bridge (Node.js) running HTTP Proxy on `8081` and WebSocket-to-TCP Gateway on `8080`.
- **Consequences**: Pure browser isolation without requiring browser extensions or insecure NPAPI desktop plugins.

---

## ADR-002: Universal Host-Based Path Reverse Proxy (`/host/<domain>/...`)
- **Context**: Different Gunny servers format resource URLs differently (e.g. Subdomains vs Subpaths). Query-string proxies (`/proxy?url=...`) break when relative SWF paths lack query parameters.
- **Decision**: Implement `/host/<domain>/<path>` routing in `server/bridge.js` where the target domain is part of the URL path itself.
- **Consequences**: All relative asset requests emitted by ActionScript (e.g. `../ui/spain/swf/ddthallIcon.swf`) resolve naturally through the proxy without path mangling.

---

## ADR-003: Pure Binary Streaming for ZLIB-Compressed XML Assets
- **Context**: Gunny loads template files (`TemplateAllList.xml`, `CardInfoList.xml`, `ShopItemList.xml`) that have `.xml` extensions but contain raw ZLIB-compressed binary bytearrays (`ByteArray`).
- **Decision**: Restrict text decoding and URL rewriting strictly to `config*.xml`. All other `.xml` and binary files must be piped untouched as raw Node.js `Buffer` objects.
- **Consequences**: Completely eliminated 12% and 100% loading hangs caused by UTF-8 string encoding corrupting binary byte streams.

---

## ADR-004: Pristine One-Time Key Extraction via Background XHR
- **Context**: Private Gunny servers issue single-use session keys on `/play/...`. If the open Chrome tab loads Flash first, the key is consumed, causing `BaseInterface.LoginAndUpdate.Try` failures in the Web Player.
- **Decision**: When syncing sessions, execute a background `XMLHttpRequest` with existing browser session cookies to retrieve a freshly minted, unconsumed `key` from the server.
- **Consequences**: Guaranteed 100% login success (`Tank.Request.Login.Success`) regardless of Chrome tab state.

---

## ADR-005: Vietnamese Unicode Font Embedding
- **Context**: Ruffle WebAssembly cannot access local OS system fonts, causing Vietnamese diacritics to render as empty boxes or broken glyphs.
- **Decision**: Bundle `Arial.ttf` and `Tahoma.ttf` in `public/fonts/` and register them synchronously in Ruffle's `fontSources` configuration before player mount.
- **Consequences**: Crystal-clear Vietnamese typography across all game menus, chat dialogues, and damage text.
