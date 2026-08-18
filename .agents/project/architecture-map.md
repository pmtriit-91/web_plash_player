# Web Flash Player Pro — Architecture Map

This document details the system topology, data flow, and runtime interaction between components.

```
+-----------------------------------------------------------------------------------+
|                              Web Browser (Chrome / Safari)                         |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  |                   Frontend Web Application (Vite / Port 5173)               |  |
|  |  +-------------------+  +---------------------+  +-----------------------+  |  |
|  |  | Glassmorphism UI  |  | Game Presets & Sync |  | Gaming Key Lock Engine|  |  |
|  |  +-------------------+  +---------------------+  +-----------------------+  |  |
|  |  +-----------------------------------------------------------------------+  |  |
|  |  |                    Ruffle Flash Player (WebAssembly Engine)           |  |  |
|  |  |  - WebGL2 Graphics Renderer (60 FPS)                                  |  |  |
|  |  |  - Embedded Vietnamese TrueType Fonts (Arial, Tahoma)                 |  |  |
|  |  |  - ActionScript 2/3 Virtual Machine                                   |  |  |
|  |  |  - WebSocket Socket Proxy Client (ws://localhost:8080)               |  |  |
|  |  +-----------------------------------------------------------------------+  |  |
|  +---------------------------------------+-------------------------------------+  |
+------------------------------------------|----------------------------------------+
                                           |
                   +-----------------------+-----------------------+
                   | HTTP Requests (Assets)                        | WebSockets (Packets)
                   v                                               v
+-----------------------------------------------------------------------------------+
|                        Universal Network Bridge (Node.js)                         |
|                                                                                   |
|  +------------------------------------------+  +-------------------------------+  |
|  | HTTP Asset Proxy Server (Port 8081)      |  | WebSocket-to-TCP Gateway      |  |
|  |  - Universal Path Router (/host/<domain>) |  | (Port 8080)                   |  |
|  |  - ZLIB Binary Buffer Streamer           |  |  - Packet Forwarder           |  |
|  |  - Dynamic XML Config Rewriter           |  |  - Smart Fallback Router      |  |
|  |  - 1-Click Session Extractor (XHR / OSA) |  |    (Target: 15.235.193.106)   |  |
|  +------------------------------------------+  +-------------------------------+  |
+-----------------------------------------------------------------------------------+
                   |                                               |
                   | Proxied HTTP / CDN Assets                     | Raw TCP Socket Stream
                   v                                               v
+---------------------------------------------+  +----------------------------------+
|    Remote Game Web / CDN Servers            |  |    Remote Game Battle Servers    |
|    - gunny.vcdn.vn                          |  |    - 15.235.193.106:25565        |
|    - s737.gn.zing.vn                        |  |    - Zing Server 737:9200        |
|    - 123gn.net                              |  |                                  |
+---------------------------------------------+  +----------------------------------+
```
