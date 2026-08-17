/**
 * Gunny & Flash Games WebSocket-to-TCP Proxy Bridge + Smart Asset & Chrome Session Sync Proxy
 * Universal Agent OS - Web Flash Player Engine
 */

import http from 'http';
import https from 'https';
import net from 'net';
import { URL } from 'url';
import { exec } from 'child_process';
import { promisify } from 'util';
import { WebSocketServer, WebSocket } from 'ws';

const execAsync = promisify(exec);

const HTTP_PORT = process.env.BRIDGE_HTTP_PORT || 8081;
const WS_PORT = process.env.BRIDGE_WS_PORT || 8080;

/**
 * Helper to fetch a URL following HTTP redirects
 */
async function fetchWithRedirects(targetUrl, maxRedirects = 5, customHeaders = {}) {
  let currentUrl = targetUrl;
  let redirects = 0;

  while (redirects < maxRedirects) {
    const parsed = new URL(currentUrl);
    const isHttps = parsed.protocol === 'https:';
    const httpModule = isHttps ? https : http;

    const headers = {
      'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Accept': '*/*',
      'Referer': `${parsed.protocol}//${parsed.host}/`,
      ...customHeaders
    };

    const res = await new Promise((resolve, reject) => {
      const req = httpModule.request(currentUrl, { method: 'GET', headers }, (res) => {
        resolve(res);
      });
      req.on('error', reject);
      req.end();
    });

    if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
      currentUrl = new URL(res.headers.location, currentUrl).toString();
      redirects++;
      continue;
    }

    return { response: res, finalUrl: currentUrl };
  }

  throw new Error('Too many redirects');
}

// 1. HTTP Server for Status, Smart Inspector, Chrome Sync, and CORS Proxy
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
      version: '1.2.0',
      wsPort: WS_PORT,
      uptime: process.uptime()
    }, null, 2));
    return;
  }

  // Chrome 1-Click Session Sync: /sync-zing-session?sid=737
  if (reqUrl.pathname === '/sync-zing-session') {
    try {
      const sid = reqUrl.searchParams.get('sid') || '737';
      const script = `tell application "Google Chrome" to execute front window's active tab javascript "(() => { var xhr = new XMLHttpRequest(); xhr.open('GET', '/play-game?_svid=${sid}&checkAgree=True', false); xhr.send(null); return xhr.responseText; })()"`;
      
      const { stdout } = await execAsync(`osascript -e ${JSON.stringify(script)}`);
      const sessionData = JSON.parse(stdout.trim());

      if (sessionData.ret === 1 && sessionData.url) {
        // Fetch the game Default.aspx to extract the exact Loading.swf and Flashvars
        const { response: pageRes } = await fetchWithRedirects(sessionData.url);
        let html = '';
        for await (const chunk of pageRes) html += chunk.toString('utf-8');

        // Extract Loading.swf
        const swfMatch = /src=['"]([^'"]+Loading\.swf[^'"]*)['"]/i.exec(html) || /value=['"]([^'"]+Loading\.swf[^'"]*)['"]/i.exec(html);
        const flashvarsMatch = /flashvars=['"]([^'"]*)['"]/i.exec(html);

        let swfUrl = swfMatch ? swfMatch[1] : null;
        let flashvars = {};
        if (flashvarsMatch) {
          const params = new URLSearchParams(flashvarsMatch[1]);
          for (const [k, v] of params.entries()) flashvars[k] = v;
        }

        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          ok: true,
          serverId: sid,
          serverUrl: sessionData.url,
          swfUrl: swfUrl || `https://res${sid}.gn.zing.vn/flash/Loading.swf`,
          proxiedSwfUrl: `http://localhost:${HTTP_PORT}/proxy?url=${encodeURIComponent(swfUrl || `https://res${sid}.gn.zing.vn/flash/Loading.swf`)}`,
          flashvars,
          message: 'Đã tự động đồng bộ phiên chơi từ Chrome thành công!'
        }));
        return;
      }

      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: 'Không lấy được phiên chơi. Hãy chắc chắn tab Chrome đang mở trang chọn server Gunny.' }));
    } catch (e) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
    return;
  }

  // Smart URL Inspector: /inspect-url?url=...
  if (reqUrl.pathname === '/inspect-url') {
    const targetUrl = reqUrl.searchParams.get('url');
    if (!targetUrl) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Missing "url" query parameter' }));
      return;
    }

    try {
      const { response: proxyRes, finalUrl } = await fetchWithRedirects(targetUrl);
      const contentType = (proxyRes.headers['content-type'] || '').toLowerCase();

      // Collect data chunks
      const chunks = [];
      for await (const chunk of proxyRes) {
        chunks.push(chunk);
        if (chunks.reduce((acc, c) => acc + c.length, 0) > 1024 * 1024) break;
      }
      const buffer = Buffer.concat(chunks);

      // Check if it's a binary SWF (magic bytes: FWS, CWS, ZWS)
      const magic = buffer.subarray(0, 3).toString('ascii');
      const isSwfBinary = magic === 'FWS' || magic === 'CWS' || magic === 'ZWS' || contentType.includes('shockwave-flash');

      if (isSwfBinary) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          ok: true,
          type: 'swf',
          finalUrl,
          swfUrl: finalUrl,
          flashvars: {}
        }));
        return;
      }

      // If it's HTML, parse it for SWF files & Flashvars
      const htmlText = buffer.toString('utf-8');
      
      const isLoginPage = finalUrl.includes('login') || 
                          finalUrl.includes('id.zing.vn') || 
                          htmlText.includes('name="password"') || 
                          htmlText.includes('id="login"') ||
                          htmlText.includes('dang-nhap') ||
                          htmlText.includes('id-levelup');

      // Search for SWF URLs in the HTML
      const swfRegex = /(?:src|data|movie|value)=["']([^"']+\.swf(?:\?[^"']*)?)["']/gi;
      const swfObjectRegex = /swfobject\.embedSWF\s*\(\s*["']([^"']+)["']/gi;
      
      const foundSwfs = [];
      let match;
      while ((match = swfRegex.exec(htmlText)) !== null) {
        foundSwfs.push(match[1]);
      }
      while ((match = swfObjectRegex.exec(htmlText)) !== null) {
        foundSwfs.push(match[1]);
      }

      // Search for flashvars in HTML
      const flashvarsRegex = /flashvars\s*[:=]\s*["']([^"']+)["']/i;
      let extractedFlashvars = {};

      const fvMatch = flashvarsRegex.exec(htmlText);
      if (fvMatch) {
        const params = new URLSearchParams(fvMatch[1]);
        for (const [k, v] of params.entries()) {
          extractedFlashvars[k] = v;
        }
      }

      if (foundSwfs.length > 0) {
        const rawSwf = foundSwfs[0];
        const resolvedSwfUrl = new URL(rawSwf, finalUrl).toString();

        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          ok: true,
          type: 'html_with_flash',
          finalUrl,
          swfUrl: resolvedSwfUrl,
          allFoundSwfs: foundSwfs.map(s => new URL(s, finalUrl).toString()),
          flashvars: extractedFlashvars,
          message: 'Đã tìm thấy tệp Flash (.swf) nhúng trong trang web!'
        }));
        return;
      }

      if (isLoginPage) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          ok: false,
          type: 'login_required',
          finalUrl,
          message: 'Trang web này yêu cầu Đăng nhập tài khoản (Zing ID/Session Cookie).'
        }));
        return;
      }

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        ok: false,
        type: 'html_no_flash',
        finalUrl,
        message: 'Trang web không chứa tệp Flash (.SWF) nào.'
      }));

    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: err.message }));
    }
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
      const { response: proxyRes, finalUrl } = await fetchWithRedirects(targetUrl);

      res.writeHead(proxyRes.statusCode || 200, {
        'Content-Type': proxyRes.headers['content-type'] || 'application/octet-stream',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Expose-Headers': '*',
        'Cache-Control': 'public, max-age=86400',
        'X-Final-Url': finalUrl
      });

      proxyRes.pipe(res);
    } catch (err) {
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Proxy request failed', details: err.message }));
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
