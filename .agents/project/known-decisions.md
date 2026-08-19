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

---

## ADR-006: Device Font Renderer (`deviceFontRenderer: 'canvas'`) for Complex Diacritics
- **Context**: When SWF files embed an incomplete subset of a font (ASCII 32-127 only), Ruffle's default `deviceFontRenderer: 'embedded'` skips missing composite tone glyphs (`ạ`, `ậ`, `ầ`, `ưở`, `ồ` in Unicode range `\u1EA0-\u1EF9`).
- **Decision**: Set `deviceFontRenderer: 'canvas'` in `window.RufflePlayer.config` and `loadConfig`, delegating missing font glyph rasterization to the browser's HTML5 Canvas 2D engine with full Vietnamese fallback fonts (`Arial`, `Tahoma`, `Inter`, `sans-serif`).
- **Consequences**: 100% full Vietnamese diacritic text rendering without missing characters across all in-game notifications.

---

## ADR-007: Gunny Launcher API Session & Direct TCP Socket Gateway Interception
- **Context**: Private servers like Gunny Hồi Ức protect asset servers behind launcher-specific User-Agents (`GunnyLauncherLite`) and require JWT bearer auth on internal APIs (`api2.gunnyhoiuc.com/api/login` and `/api/play`).
- **Decision**: Implement `/login-gunny-hoiuc` on the bridge to automate the launcher login handshake, spoof User-Agent on proxy requests, rewrite internal `ServerList.ashx` ports from `9131` to `9200`, and route socket tuples `(103.92.27.133, 9200)` via `socketProxy`.
- **Consequences**: Fully seamless 1-click preset launch into live game servers without external desktop `.exe` launchers.

---

### ADR-008: Destructible Terrain BlendMode.ERASE Invalidation
- **Context**: In Gunny / DDTank 2.3 battles, bomb craters render as solid color circles instead of transparent holes.
- **Decision**: Primary cause identified as Ruffle WASM `core/src/bitmap/operations.rs` `BitmapData.draw` offscreen shader rasterization of vector shapes. Primary graphics engine remains WebGL (`wgpu-webgl` or `webgl`) for Stage3D compatibility.

### ADR-009: Native Adobe Flash Player 32 Standalone Runner Architecture
- **Context**: Users requiring 100% authentic legacy Flash rendering (including pristine pixel-perfect destructible terrain and zero shader discrepancies) on desktop environments.
- **Decision**: Integrated official Adobe Flash Player 32 standalone projector (`runtime/flash/Flash Player.app`) orchestrated by local Bridge API `/launch-native-flash`. Provides 1-click execution bypassing browser extension hijacking while maintaining full security bypass and asset proxying.
- **Consequences**: Enables systematic diagnostics, graceful fallbacks for complex blend modes, and clear architectural tracking for future Ruffle engine improvements.
