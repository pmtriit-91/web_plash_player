/**
 * Gunny & Flash Games WebSocket-to-TCP Proxy Bridge + Smart Asset, XML Rewriter & Chrome Session Sync Proxy
 * Universal Agent OS - Web Flash Player Engine
 */

import http from 'http';
import https from 'https';
import net from 'net';
import { URL } from 'url';
import { spawn } from 'child_process';
import { WebSocketServer, WebSocket } from 'ws';

const HTTP_PORT = process.env.BRIDGE_HTTP_PORT || 8081;
const WS_PORT = process.env.BRIDGE_WS_PORT || 8080;

/**
 * Execute AppleScript cleanly via stdin to avoid shell escaping issues
 */
function runAppleScript(script) {
  return new Promise((resolve, reject) => {
    const child = spawn('osascript', []);
    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (d) => { stdout += d; });
    child.stderr.on('data', (d) => { stderr += d; });

    child.on('close', (code) => {
      if (code === 0) {
        resolve(stdout.trim());
      } else {
        reject(new Error(stderr.trim() || `AppleScript exited with code ${code}`));
      }
    });

    child.stdin.write(script);
    child.stdin.end();
  });
}

/**
 * Helper to fetch a URL following HTTP redirects with intelligent referer
 */
async function fetchWithRedirects(targetUrl, maxRedirects = 5, customHeaders = {}) {
  let currentUrl = targetUrl;
  let redirects = 0;

  while (redirects < maxRedirects) {
    const parsed = new URL(currentUrl);
    const isHttps = parsed.protocol === 'https:';
    const httpModule = isHttps ? https : http;

    let referer = `${parsed.protocol}//${parsed.host}/`;
    if (parsed.hostname.endsWith('zing.vn') || parsed.hostname.endsWith('vcdn.vn')) {
      referer = 'https://id-levelup.gn.zing.vn/server-game';
    }

    const headers = {
      'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Accept': '*/*',
      'Referer': referer,
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

/**
 * Extract Flash SWF and Flashvars from HTML
 */
function extractFlashFromHtml(htmlText, finalUrl) {
  let swfRawUrl = null;
  let extractedFlashvars = {};

  // 1. Check <param name="movie" value='...' /> or value="..."
  const paramMovieMatch = /<param[^>]*name=["'](?:movie|src)["'][^>]*value=["']([^"']+)["']/i.exec(htmlText) ||
                          /<param[^>]*value=["']([^"']+)["'][^>]*name=["'](?:movie|src)["']/i.exec(htmlText);
  if (paramMovieMatch) {
    swfRawUrl = paramMovieMatch[1];
  }

  // 2. Check <embed src='...' ...>
  if (!swfRawUrl) {
    const embedSrcMatch = /<embed[^>]*src=["']([^"']+)["']/i.exec(htmlText);
    if (embedSrcMatch) {
      swfRawUrl = embedSrcMatch[1];
    }
  }

  // 3. Check swfobject.embedSWF("...")
  if (!swfRawUrl) {
    const swfObjMatch = /swfobject\.embedSWF\s*\(\s*["']([^"']+)["']/i.exec(htmlText);
    if (swfObjMatch) {
      swfRawUrl = swfObjMatch[1];
    }
  }

  // 4. Extract Flashvars from <param name="FlashVars" value="..."> or embed
  const fvParamMatch = /<param[^>]*name=["']flashvars["'][^>]*value=["']([^"']*)["']/i.exec(htmlText) ||
                       /<param[^>]*value=["']([^"']*)["'][^>]*name=["']flashvars["']/i.exec(htmlText) ||
                       /<embed[^>]*flashvars=["']([^"']*)["']/i.exec(htmlText);
  if (fvParamMatch && fvParamMatch[1]) {
    const fvParams = new URLSearchParams(fvParamMatch[1]);
    for (const [k, v] of fvParams.entries()) {
      extractedFlashvars[k] = v;
    }
  }

  if (swfRawUrl) {
    const fullSwfUrl = new URL(swfRawUrl, finalUrl).toString();
    const parsedSwfUrl = new URL(fullSwfUrl);

    for (const [k, v] of parsedSwfUrl.searchParams.entries()) {
      if (k === 'config') {
        extractedFlashvars[k] = `http://localhost:${HTTP_PORT}/proxy?url=${encodeURIComponent(v)}`;
      } else {
        extractedFlashvars[k] = v;
      }
    }

    const cleanSwfUrl = `${parsedSwfUrl.origin}${parsedSwfUrl.pathname}`;
    const baseUrl = cleanSwfUrl.substring(0, cleanSwfUrl.lastIndexOf('/') + 1);

    return {
      found: true,
      cleanSwfUrl,
      fullSwfUrl,
      flashvars: extractedFlashvars,
      baseUrl
    };
  }

  return { found: false };
}

// 1. HTTP Server for Status, Smart Inspector, Chrome Sync, Dynamic XML Rewriter, and CORS Proxy
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
      version: '1.6.0',
      wsPort: WS_PORT,
      uptime: process.uptime()
    }, null, 2));
    return;
  }

  // Chrome 1-Click Session Sync: /sync-zing-session?sid=737
  if (reqUrl.pathname === '/sync-zing-session') {
    try {
      const sid = reqUrl.searchParams.get('sid') || '737';
      const appleScript = `tell application "Google Chrome"
  repeat with w in windows
    repeat with t in tabs of w
      if URL of t contains "id-levelup.gn.zing.vn" then
        tell t to return (execute javascript "(() => { var xhr = new XMLHttpRequest(); xhr.open('GET', '/play-game?_svid=${sid}&checkAgree=True', false); xhr.send(null); return xhr.responseText; })()")
      end if
    end repeat
  end repeat
  return "NOT_FOUND"
end tell`;

      const outputText = await runAppleScript(appleScript);

      if (outputText === 'NOT_FOUND' || !outputText) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: false, error: 'Không tìm thấy tab Gunny (id-levelup.gn.zing.vn) nào đang mở trong Chrome.' }));
        return;
      }

      const sessionData = JSON.parse(outputText);

      if (sessionData.ret === 1 && sessionData.url) {
        const { response: pageRes } = await fetchWithRedirects(sessionData.url);
        let html = '';
        for await (const chunk of pageRes) html += chunk.toString('utf-8');

        const extracted = extractFlashFromHtml(html, sessionData.url);

        if (extracted.found) {
          const proxiedSwf = `http://localhost:${HTTP_PORT}/proxy?url=${encodeURIComponent(extracted.cleanSwfUrl)}`;
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({
            ok: true,
            serverId: sid,
            serverUrl: sessionData.url,
            swfUrl: extracted.cleanSwfUrl,
            proxiedSwfUrl: proxiedSwf,
            flashvars: extracted.flashvars,
            baseUrl: extracted.baseUrl,
            message: 'Đã tự động đồng bộ phiên chơi từ Chrome thành công!'
          }));
          return;
        }
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
      const extracted = extractFlashFromHtml(htmlText, finalUrl);

      if (extracted.found) {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          ok: true,
          type: 'html_with_flash',
          finalUrl,
          swfUrl: extracted.cleanSwfUrl,
          proxiedSwfUrl: `http://localhost:${HTTP_PORT}/proxy?url=${encodeURIComponent(extracted.cleanSwfUrl)}`,
          flashvars: extracted.flashvars,
          baseUrl: extracted.baseUrl,
          message: 'Đã tìm thấy tệp Flash (.swf) và tham số Gunny nhúng trong trang web!'
        }));
        return;
      }

      const isLoginPage = finalUrl.includes('login') || 
                          finalUrl.includes('id.zing.vn') || 
                          htmlText.includes('name="password"') || 
                          htmlText.includes('id="login"') ||
                          htmlText.includes('dang-nhap') ||
                          htmlText.includes('id-levelup');

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

  // CORS Asset Proxy with Dynamic XML Rewriter: /proxy?url=http://example.com/asset.swf
  if (reqUrl.pathname === '/proxy') {
    const targetUrl = reqUrl.searchParams.get('url');
    if (!targetUrl) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Missing "url" query parameter' }));
      return;
    }

    try {
      const { response: proxyRes, finalUrl } = await fetchWithRedirects(targetUrl);
      const isXml = (proxyRes.headers['content-type'] || '').includes('xml') || targetUrl.includes('.xml');

      if (isXml) {
        let xmlContent = '';
        for await (const chunk of proxyRes) {
          xmlContent += chunk.toString('utf-8');
        }

        // Dynamically rewrite FLASHSITE, SITE, REQUEST_PATH, POLICY_FILES to route through Proxy
        const rewrittenXml = xmlContent.replace(
          /value=["'](https?:\/\/[^"']+)["']/gi,
          (match, originalUrl) => {
            if (originalUrl.includes('vcdn.vn') || originalUrl.includes('zing.vn') || originalUrl.includes('7road.com')) {
              return `value="http://localhost:${HTTP_PORT}/proxy?url=${encodeURIComponent(originalUrl)}"`;
            }
            return match;
          }
        );

        res.writeHead(200, {
          'Content-Type': 'application/xml; charset=utf-8',
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Headers': '*',
          'Cache-Control': 'no-cache',
          'X-Rewritten-By': 'Gunny-Bridge-Proxy'
        });
        res.end(rewrittenXml);
        return;
      }

      // Normal binary streaming proxy (SWF, PNG, MP3, etc.)
      res.writeHead(proxyRes.statusCode || 200, {
        'Content-Type': proxyRes.headers['content-type'] || 'application/octet-stream',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': '*',
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
