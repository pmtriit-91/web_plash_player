/**
 * Universal Gunny & Flash Games WebSocket-to-TCP Proxy Bridge
 * Supports Zing Gunny, 123gn.net, Private Servers, and Custom Flash Games
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
 * Execute AppleScript cleanly via stdin
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
    } else if (parsed.hostname.includes('123gn.net')) {
      referer = 'https://123gn.net/play/1001';
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

  const paramMovieMatch = /<param[^>]*name=["'](?:movie|src)["'][^>]*value=["']([^"']+)["']/i.exec(htmlText) ||
                          /<param[^>]*value=["']([^"']+)["'][^>]*name=["'](?:movie|src)["']/i.exec(htmlText);
  if (paramMovieMatch) {
    swfRawUrl = paramMovieMatch[1];
  }

  if (!swfRawUrl) {
    const embedSrcMatch = /<embed[^>]*src=["']([^"']+)["']/i.exec(htmlText);
    if (embedSrcMatch) {
      swfRawUrl = embedSrcMatch[1];
    }
  }

  if (!swfRawUrl) {
    const swfObjMatch = /swfobject\.embedSWF\s*\(\s*["']([^"']+)["']/i.exec(htmlText);
    if (swfObjMatch) {
      swfRawUrl = swfObjMatch[1];
    }
  }

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
        const configUrl = new URL(v);
        const subDomainMatch = /^(s[0-9]+)\.gn\.zing\.vn$/i.exec(configUrl.hostname);
        if (subDomainMatch) {
          extractedFlashvars[k] = `http://localhost:${HTTP_PORT}/${subDomainMatch[1]}${configUrl.pathname}`;
        } else {
          extractedFlashvars[k] = `http://localhost:${HTTP_PORT}/proxy?url=${encodeURIComponent(v)}`;
        }
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

// 1. HTTP Server for Status, Path-based Asset Proxy, and Universal Session Sync
const server = http.createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS, HEAD');
  res.setHeader('Access-Control-Allow-Headers', '*');
  res.setHeader('Access-Control-Expose-Headers', '*');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  const reqUrl = new URL(req.url, `http://localhost:${HTTP_PORT}`);
  const pathname = reqUrl.pathname;

  // Health check endpoint
  if (pathname === '/health' || pathname === '/') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      status: 'active',
      service: 'Universal Web Flash Player Bridge',
      version: '3.1.0',
      wsPort: WS_PORT,
      uptime: process.uptime()
    }, null, 2));
    return;
  }

  // Universal Gunny 1-Click Session Sync from Chrome (Zing, 123gn.net, Private Servers)
  if (pathname === '/sync-zing-session' || pathname === '/sync-gunny-session') {
    try {
      const sid = reqUrl.searchParams.get('sid') || '737';
      const jsExtractDirect = `(() => {
        var html = document.documentElement.innerHTML;
        var swf = (typeof swfPath !== 'undefined') ? swfPath : '';
        if (!swf) {
          var el = document.querySelector('object, embed');
          if (el) swf = el.getAttribute('data') || el.getAttribute('movie') || el.src || '';
        }
        if (!swf) {
          var m = html.match(/(https?:\\/\\/[^"'\\s]+\\/Loading\\.swf)/i);
          if (m) swf = m[1];
        }
        if (!swf) swf = 'https://123gn.net/flash3/Loading.swf';

        var fv = null;
        if (typeof flashvars !== 'undefined' && typeof flashvars === 'object') {
          fv = Object.assign({}, flashvars);
        }
        if (!fv) {
          var mFvObj = html.match(/flashvars\\s*=\\s*({[\\s\\S]*?});/i);
          if (mFvObj) {
            try { eval('fv = ' + mFvObj[1]); } catch(e){}
          }
        }
        if (!fv) {
          var mFvStr = html.match(/flashvars[\"'\s]*[:=][\"'\s]*([a-zA-Z0-9_=&%\\/:.\\-]+)/i);
          if (mFvStr) {
            var sp = new URLSearchParams(mFvStr[1].replace(/&amp;/g, '&'));
            fv = {};
            for (var pair of sp.entries()) fv[pair[0]] = pair[1];
          }
        }
        return JSON.stringify({ type: 'direct', swfUrl: swf, flashvars: fv || {}, pageUrl: window.location.href });
      })()`;

      const appleScript = `tell application "Google Chrome"
  repeat with w in windows
    repeat with t in tabs of w
      set tabUrl to URL of t
      if tabUrl contains "id-levelup.gn.zing.vn" then
        tell t to return (execute javascript "(() => { var xhr = new XMLHttpRequest(); xhr.open('GET', '/play-game?_svid=${sid}&checkAgree=True', false); xhr.send(null); return JSON.stringify({ type: 'zing', data: JSON.parse(xhr.responseText) }); })()")
      else if tabUrl contains "123gn.net" or tabUrl contains "/play/" or tabUrl contains "Loading.swf" or tabUrl contains "gunny" then
        tell t to return (execute javascript ${JSON.stringify(jsExtractDirect)})
      end if
    end repeat
  end repeat
  return "NOT_FOUND"
end tell`;

      const outputText = await runAppleScript(appleScript);

      if (outputText === 'NOT_FOUND' || !outputText) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: false, error: 'Không tìm thấy tab Gunny (Zing hoặc 123gn.net) nào đang mở trong Chrome.' }));
        return;
      }

      const syncResult = JSON.parse(outputText);

      if (syncResult.type === 'zing' && syncResult.data && syncResult.data.ret === 1) {
        const sessionUrl = syncResult.data.url;
        const { response: pageRes } = await fetchWithRedirects(sessionUrl);
        let html = '';
        for await (const chunk of pageRes) html += chunk.toString('utf-8');

        const extracted = extractFlashFromHtml(html, sessionUrl);

        if (extracted.found) {
          const proxiedSwf = `http://localhost:${HTTP_PORT}/res${sid}/flash/Loading.swf`;
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({
            ok: true,
            serverType: 'zing',
            serverId: sid,
            serverUrl: sessionUrl,
            swfUrl: extracted.cleanSwfUrl,
            proxiedSwfUrl: proxiedSwf,
            flashvars: extracted.flashvars,
            baseUrl: `http://localhost:${HTTP_PORT}/res${sid}/flash/`,
            message: 'Đã tự động đồng bộ phiên chơi Zing Gunny từ Chrome thành công!'
          }));
          return;
        }
      } else if (syncResult.type === 'direct' && syncResult.swfUrl) {
        const cleanSwf = syncResult.swfUrl;
        const fv = syncResult.flashvars || {};
        
        // Proxy config URL if present
        if (fv.config) {
          fv.config = `http://localhost:${HTTP_PORT}/proxy?url=${encodeURIComponent(fv.config)}`;
        }

        const proxiedSwf = `http://localhost:${HTTP_PORT}/proxy?url=${encodeURIComponent(cleanSwf)}`;
        const baseUrl = cleanSwf.substring(0, cleanSwf.lastIndexOf('/') + 1);

        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          ok: true,
          serverType: 'private',
          serverUrl: syncResult.pageUrl,
          swfUrl: cleanSwf,
          proxiedSwfUrl: proxiedSwf,
          flashvars: fv,
          baseUrl: `http://localhost:${HTTP_PORT}/proxy?url=${encodeURIComponent(baseUrl)}`,
          message: `Đã tự động đồng bộ phiên chơi Gunny (${new URL(syncResult.pageUrl).hostname}) từ Chrome!`
        }));
        return;
      }

      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: 'Không thể trích xuất thông tin game từ tab Chrome đang mở.' }));
    } catch (e) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
    return;
  }

  // Path-based Proxy Routing for Gunny
  let targetUrl = null;

  if (pathname.startsWith('/vcdn/')) {
    targetUrl = `https://gunny.vcdn.vn/${pathname.substring('/vcdn/'.length)}${reqUrl.search}`;
  } else if (/^\/(quest[0-9]+)\//i.test(pathname)) {
    const match = /^\/(quest[0-9]+)\/(.*)/i.exec(pathname);
    targetUrl = `https://${match[1]}.gn.zing.vn/${match[2]}${reqUrl.search}`;
  } else if (/^\/(s[0-9]+)\//i.test(pathname)) {
    const match = /^\/(s[0-9]+)\/(.*)/i.exec(pathname);
    targetUrl = `https://${match[1]}.gn.zing.vn/${match[2]}${reqUrl.search}`;
  } else if (/^\/(res[0-9]+)\//i.test(pathname)) {
    const match = /^\/(res[0-9]+)\/(.*)/i.exec(pathname);
    targetUrl = `https://${match[1]}.gn.zing.vn/${match[2]}${reqUrl.search}`;
  } else if (/^\/(assist[0-9]+)\//i.test(pathname)) {
    const match = /^\/(assist[0-9]+)\/(.*)/i.exec(pathname);
    targetUrl = `https://${match[1]}.gn.zing.vn/${match[2]}${reqUrl.search}`;
  } else if (pathname === '/proxy') {
    targetUrl = reqUrl.searchParams.get('url');
  }

  if (targetUrl) {
    try {
      const { response: proxyRes, finalUrl } = await fetchWithRedirects(targetUrl);
      const isXml = (proxyRes.headers['content-type'] || '').includes('xml') || targetUrl.includes('.xml');

      if (isXml) {
        let xmlContent = '';
        for await (const chunk of proxyRes) {
          xmlContent += chunk.toString('utf-8');
        }

        // Clean Path-based XML Rewriter for Zing and Universal Proxy Rewriter for other domains
        const rewrittenXml = xmlContent
          .replace(/https?:\/\/gunny\.vcdn\.vn\/flash\//gi, `http://localhost:${HTTP_PORT}/vcdn/flash/`)
          .replace(/https?:\/\/gunny\.vcdn\.vn\//gi, `http://localhost:${HTTP_PORT}/vcdn/`)
          .replace(/https?:\/\/(quest[0-9]+)\.gn\.zing\.vn\//gi, `http://localhost:${HTTP_PORT}/$1/`)
          .replace(/https?:\/\/(s[0-9]+)\.gn\.zing\.vn\//gi, `http://localhost:${HTTP_PORT}/$1/`)
          .replace(/https?:\/\/(res[0-9]+)\.gn\.zing\.vn\//gi, `http://localhost:${HTTP_PORT}/$1/`)
          .replace(/https?:\/\/(assist[0-9]+)\.gn\.zing\.vn\//gi, `http://localhost:${HTTP_PORT}/$1/`)
          .replace(/value=["'](https?:\/\/[^"']+)["']/gi, (match, url) => {
            if (url.startsWith(`http://localhost:${HTTP_PORT}`)) return match;
            return `value="http://localhost:${HTTP_PORT}/proxy?url=${encodeURIComponent(url)}"`;
          });

        res.writeHead(200, {
          'Content-Type': 'application/xml; charset=utf-8',
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Headers': '*',
          'Cache-Control': 'no-cache',
          'X-Rewritten-By': 'Gunny-Bridge-Universal-Proxy'
        });
        res.end(rewrittenXml);
        return;
      }

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
      res.end(JSON.stringify({ error: 'Proxy request failed', details: err.message, targetUrl }));
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
