/**
 * Gunny & Flash Games WebSocket-to-TCP Proxy Bridge + Asset CORS Proxy
 * Universal Agent OS - Web Flash Player Engine
 */

import http from 'http';
import net from 'net';
import { URL } from 'url';
import { WebSocketServer, WebSocket } from 'ws';

const HTTP_PORT = process.env.BRIDGE_HTTP_PORT || 8081;
const WS_PORT = process.env.BRIDGE_WS_PORT || 8080;

// 1. HTTP Server for Status & CORS Asset Proxy
const server = http.createServer(async (req, res) => {
  // Add universal CORS headers
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, HEAD');
  res.setHeader('Access-Control-Allow-Headers', '*');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  const reqUrl = new URL(req.url, `http://localhost:${HTTP_PORT}`);

  // Health check endpoint
  if (reqUrl.pathname === '/health' || reqUrl.pathname === '/') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      status: 'active',
      service: 'Web Flash Player Network Bridge',
      version: '1.0.0',
      wsPort: WS_PORT,
      uptime: process.uptime()
    }, null, 2));
    return;
  }

  // CORS Asset Proxy: /proxy?url=http://example.com/asset.swf
  if (reqUrl.pathname === '/proxy') {
    const targetUrl = reqUrl.searchParams.get('url');
    if (!targetUrl) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Missing "url" query parameter' }));
      return;
    }

    try {
      const parsedTarget = new URL(targetUrl);
      const isHttps = parsedTarget.protocol === 'https:';
      const httpModule = isHttps ? await import('https') : await import('http');

      const proxyReq = httpModule.get(targetUrl, (proxyRes) => {
        res.writeHead(proxyRes.statusCode || 200, {
          'Content-Type': proxyRes.headers['content-type'] || 'application/octet-stream',
          'Access-Control-Allow-Origin': '*',
          'Cache-Control': 'public, max-age=86400'
        });
        proxyRes.pipe(res);
      });

      proxyReq.on('error', (err) => {
        res.writeHead(502, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Proxy request failed', details: err.message }));
      });
    } catch (err) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Invalid URL', details: err.message }));
    }
    return;
  }

  res.writeHead(404, { 'Content-Type': 'text/plain' });
  res.end('Not Found');
});

// 2. WebSocket-to-TCP Proxy Server for Flash Socket Connection (Gunny Game Server)
const wss = new WebSocketServer({ port: WS_PORT });

console.log(`[Bridge] WebSocket-to-TCP Gateway listening on ws://localhost:${WS_PORT}`);

wss.on('connection', (ws, req) => {
  const reqUrl = new URL(req.url, `http://localhost:${WS_PORT}`);
  const targetHost = reqUrl.searchParams.get('host') || '127.0.0.1';
  const targetPort = parseInt(reqUrl.searchParams.get('port') || '9200', 10);

  console.log(`[Bridge] New client connected. Forwarding to TCP ${targetHost}:${targetPort}`);

  // Create raw TCP connection to the game server
  const tcpSocket = net.createConnection({ host: targetHost, port: targetPort }, () => {
    console.log(`[Bridge] TCP connected to ${targetHost}:${targetPort}`);
  });

  tcpSocket.on('data', (data) => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(data);
    }
  });

  tcpSocket.on('error', (err) => {
    console.error(`[Bridge] TCP Socket Error (${targetHost}:${targetPort}):`, err.message);
    if (ws.readyState === WebSocket.OPEN) {
      ws.close(1011, `TCP connection error: ${err.message}`);
    }
  });

  tcpSocket.on('close', () => {
    console.log(`[Bridge] TCP connection closed with ${targetHost}:${targetPort}`);
    if (ws.readyState === WebSocket.OPEN) {
      ws.close();
    }
  });

  ws.on('message', (message) => {
    if (tcpSocket.writable) {
      tcpSocket.write(message);
    }
  });

  ws.on('close', () => {
    console.log(`[Bridge] WebSocket client disconnected`);
    tcpSocket.end();
  });

  ws.on('error', (err) => {
    console.error(`[Bridge] WebSocket Error:`, err.message);
    tcpSocket.destroy();
  });
});

server.listen(HTTP_PORT, () => {
  console.log(`[Bridge] HTTP Asset Proxy & Control Server listening on http://localhost:${HTTP_PORT}`);
});
