/**
 * Universal Gunny & Flash Games WebSocket-to-TCP Proxy Bridge
 * Intelligent Session Extraction & Smart Socket Routing Engine
 * Universal Agent OS - Web Flash Player Engine
 */

import http from 'http';
import https from 'https';
import net from 'net';
import zlib from 'zlib';
import { URL } from 'url';
import { spawn } from 'child_process';
import { WebSocketServer, WebSocket } from 'ws';

const HTTP_PORT = process.env.BRIDGE_HTTP_PORT || 8081;
const WS_PORT = process.env.BRIDGE_WS_PORT || 8080;

let lastDetectedGameServer = {
  host: '15.235.193.106',
  port: 25565
};

/**
 * Helper to decompress gzip/deflate/br responses seamlessly
 */
async function readTextResponse(res) {
  let stream = res;
  const encoding = res.headers ? res.headers['content-encoding'] : null;
  if (encoding === 'gzip') {
    stream = res.pipe(zlib.createGunzip());
  } else if (encoding === 'deflate') {
    stream = res.pipe(zlib.createInflate());
  } else if (encoding === 'br') {
    stream = res.pipe(zlib.createBrotliDecompress());
  }
  let text = '';
  for await (const chunk of stream) {
    text += chunk.toString('utf-8');
  }
  return text;
}

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

    const isGunnyHoiUc = currentUrl.includes('gunnyhoiuc.com');
    const headers = {
      'User-Agent': isGunnyHoiUc ? 'GunnyLauncherLite' : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Accept': '*/*',
      'Referer': currentUrl,
      ...customHeaders
    };

    try {
      const res = await new Promise((resolve, reject) => {
        const req = httpModule.request(currentUrl, { method: 'GET', headers, timeout: 6000 }, (res) => {
          resolve(res);
        });
        req.on('error', reject);
        req.on('timeout', () => { req.destroy(new Error('Timeout')); });
        req.end();
      });

      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        currentUrl = new URL(res.headers.location, currentUrl).toString();
        redirects++;
        continue;
      }

      return { response: res, finalUrl: currentUrl };
    } catch (err) {
      if (currentUrl.startsWith('https:')) {
        // Fallback to HTTP for non-SSL private server subdomains (e.g. flash8.gun321.vip, quest8...)
        currentUrl = currentUrl.replace('https:', 'http:');
        redirects++;
        continue;
      }
      throw err;
    }
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
        extractedFlashvars[k] = `http://localhost:${HTTP_PORT}/host/${configUrl.host}${configUrl.pathname}`;
      } else {
        extractedFlashvars[k] = v;
      }
    }

    const cleanSwfUrl = `${parsedSwfUrl.origin}${parsedSwfUrl.pathname}`;
    const baseUrl = `http://localhost:${HTTP_PORT}/host/${parsedSwfUrl.host}${parsedSwfUrl.pathname.substring(0, parsedSwfUrl.pathname.lastIndexOf('/') + 1)}`;

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

// 1. HTTP Server for Status, Host-based Asset Proxy, and Universal Session Sync
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
      version: '5.0.0',
      wsPort: WS_PORT,
      activeGameServer: lastDetectedGameServer,
      uptime: process.uptime()
    }, null, 2));
    return;
  }

  // Universal Gunny 1-Click Dynamic Session Sync from Chrome (Any Server / Any Domain)
  if (pathname === '/sync-zing-session' || pathname === '/sync-gunny-session') {
    try {
      const sid = reqUrl.searchParams.get('sid') || '737';
      
      // Universal Dynamic Chrome Tab Inspector (No hardcoded domain branches)
      const jsUniversalSniffer = `(() => {
        try {
          const loc = window.location;
          const ignoreDomains = ['localhost', '127.0.0.1', 'google.com', 'youtube.com', 'github.com', 'chatgpt.com', 'facebook.com', 'speedtest.net'];
          if (ignoreDomains.some(d => loc.hostname.includes(d))) return null;

          // 1. Dynamic Token & FlashData extraction (JWT / CMS based private servers)
          var token = localStorage.getItem('token');
          var flashDataStr = localStorage.getItem('flashData');
          var fData = null;
          if (flashDataStr) {
            try { fData = JSON.parse(flashDataStr); } catch(e){}
          }
          if (!fData && token) {
            var sids = [1004, 1001, 1002, 1003, 1, 2, 3];
            for (var s of sids) {
              try {
                var xhr = new XMLHttpRequest();
                xhr.open('GET', '/launcher/api/create-flashvars/' + s, false);
                xhr.setRequestHeader('Authorization', 'Bearer ' + token);
                xhr.send(null);
                if (xhr.status === 200) {
                  fData = JSON.parse(xhr.responseText);
                  if (fData && fData.swfPath) break;
                }
              } catch(e){}
            }
          }
          if (fData && fData.swfPath) {
            return JSON.stringify({
              type: 'dynamic_token',
              swfUrl: fData.swfPath,
              flashvars: fData.flashvars || {},
              pageUrl: loc.href,
              domain: loc.hostname
            });
          }

          // 2. Dynamic Zing API session check
          if (loc.hostname.includes('zing.vn')) {
            try {
              var xhrZing = new XMLHttpRequest();
              xhrZing.open('GET', '/play-game?_svid=${sid}&checkAgree=True', false);
              xhrZing.send(null);
              var zingRes = JSON.parse(xhrZing.responseText);
              if (zingRes && zingRes.ret === 1) {
                return JSON.stringify({ type: 'zing', data: zingRes, pageUrl: loc.href, domain: loc.hostname });
              }
            } catch(e){}
          }

          // 3. Dynamic HTML & Flashvars inspection
          var html = '';
          try {
            var xhrDoc = new XMLHttpRequest();
            xhrDoc.open('GET', loc.href, false);
            xhrDoc.send(null);
            html = xhrDoc.responseText || '';
          } catch(e) {
            html = document.documentElement.innerHTML;
          }
          if (!html) html = document.documentElement.innerHTML;

          var swf = '';
          var mSwf = html.match(/swfPath\\s*=\\s*[\"']([^\"']+)[\"']/i) || 
                     html.match(/(https?:\\/\\/[^\"'\\s]+\\/Loading\\.swf[a-zA-Z0-9_=&%/?.-]*)/i) ||
                     html.match(/src\\s*=\\s*[\"']([^\"']+\\.swf[^\"']*)[\"']/i);
          if (mSwf) swf = mSwf[1];

          var fv = null;
          var mFvObj = html.match(/flashvars\\s*=\\s*({[\\s\\S]*?});/i);
          if (mFvObj) {
            try { eval('fv = ' + mFvObj[1]); } catch(e){}
          }
          if (!fv) {
            var mFvStr = html.match(/flashvars[\"'\s]*[:=][\"'\s]*([a-zA-Z0-9_=&%\\/:.\\-]+)/i);
            if (mFvStr) {
              var sp = new URLSearchParams(mFvStr[1].replace(/&amp;/g, '&'));
              fv = {};
              for (var pair of sp.entries()) fv[pair[0]] = pair[1];
            }
          }

          if (swf || (fv && Object.keys(fv).length > 0)) {
            if (!swf) swf = loc.origin + '/flash3/Loading.swf';
            return JSON.stringify({
              type: 'dynamic_direct',
              swfUrl: new URL(swf, loc.href).href,
              flashvars: fv || {},
              pageUrl: loc.href,
              domain: loc.hostname
            });
          }

          return null;
        } catch(err) {
          return null;
        }
      })()`;

      const appleScript = `tell application "Google Chrome"
  repeat with w in windows
    repeat with t in tabs of w
      set res to (execute t javascript ${JSON.stringify(jsUniversalSniffer)})
      if res is not "" and res is not "null" and res is not missing value then
        return res
      end if
    end repeat
  end repeat
  return "NOT_FOUND"
end tell`;

      const outputText = await runAppleScript(appleScript);

      if (outputText === 'NOT_FOUND' || !outputText) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: false, error: 'Không tìm thấy tab web game nào đang mở trong Chrome.' }));
        return;
      }

      const syncResult = JSON.parse(outputText);

      if (syncResult.type === 'zing' && syncResult.data && syncResult.data.ret === 1) {
        const sessionUrl = syncResult.data.url;
        const { response: pageRes } = await fetchWithRedirects(sessionUrl);
        const html = await readTextResponse(pageRes);

        const extracted = extractFlashFromHtml(html, sessionUrl);

        if (extracted.found) {
          lastDetectedGameServer = { host: `s${sid}.gn.zing.vn`, port: 9200 };
          const proxiedSwf = `http://localhost:${HTTP_PORT}/host/res${sid}.gn.zing.vn/flash/Loading.swf`;
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({
            ok: true,
            serverType: 'zing',
            serverId: sid,
            serverUrl: sessionUrl,
            swfUrl: extracted.cleanSwfUrl,
            proxiedSwfUrl: proxiedSwf,
            flashvars: extracted.flashvars,
            baseUrl: `http://localhost:${HTTP_PORT}/host/res${sid}.gn.zing.vn/flash/`,
            gameServer: lastDetectedGameServer,
            message: 'Đã tự động đồng bộ phiên chơi Zing Gunny từ Chrome thành công!'
          }));
          return;
        }
      } else if ((syncResult.type === 'dynamic_direct' || syncResult.type === 'dynamic_token') && syncResult.swfUrl) {
        const cleanSwf = syncResult.swfUrl.replace(/([^:])\/\//g, '$1/');
        const parsedSwf = new URL(cleanSwf, syncResult.pageUrl);
        const fv = syncResult.flashvars || {};
        
        // Proxy config URL cleanly through dynamic /host/
        if (fv.config) {
          try {
            const parsedConfig = new URL(fv.config, syncResult.pageUrl);
            fv.config = `http://localhost:${HTTP_PORT}/host/${parsedConfig.host}${parsedConfig.pathname}`;
          } catch (e) {
            fv.config = `http://localhost:${HTTP_PORT}/proxy?url=${encodeURIComponent(fv.config)}`;
          }
        }

        const proxiedSwf = `http://localhost:${HTTP_PORT}/host/${parsedSwf.host}${parsedSwf.pathname}`;
        const baseFolder = parsedSwf.pathname.substring(0, parsedSwf.pathname.lastIndexOf('/') + 1);
        const baseUrl = `http://localhost:${HTTP_PORT}/host/${parsedSwf.host}${baseFolder}`;

        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          ok: true,
          serverType: 'universal_dynamic',
          serverUrl: syncResult.pageUrl,
          swfUrl: cleanSwf,
          proxiedSwfUrl: proxiedSwf,
          flashvars: fv,
          baseUrl: baseUrl,
          gameServer: lastDetectedGameServer,
          message: `Đã tự động đồng bộ phiên chơi Gunny (${syncResult.domain || parsedSwf.host}) từ Chrome!`
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

  // 1-Click Login & Launcher Launcher API for Gunny Hồi Ức: /login-gunny-hoiuc?user=...&pass=...
  if (pathname === '/login-gunny-hoiuc') {
    const user = reqUrl.searchParams.get('user') || 'bughunter001';
    const pass = reqUrl.searchParams.get('pass') || '123456@abcD';
    try {
      console.log(`[Bridge] 🚀 Authenticating with Gunny Hồi Ức API for user: ${user}`);
      const loginPayload = JSON.stringify({ username: user, password: pass });
      const loginReq = http.request('http://api2.gunnyhoiuc.com/api/login', {
        method: 'POST',
        headers: {
          'User-Agent': 'GunnyLauncherLite',
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(loginPayload)
        }
      }, (loginRes) => {
        let loginBody = '';
        loginRes.on('data', c => loginBody += c);
        loginRes.on('end', () => {
          try {
            const loginData = JSON.parse(loginBody);
            if (!loginData.token) {
              res.writeHead(400, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify({ ok: false, error: loginData.message || 'Đăng nhập thất bại' }));
              return;
            }

            const playPayload = JSON.stringify({ server_id: 1001 });
            const playReq = http.request('http://api2.gunnyhoiuc.com/api/play', {
              method: 'POST',
              headers: {
                'User-Agent': 'GunnyLauncherLite',
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${loginData.token}`,
                'Content-Length': Buffer.byteLength(playPayload)
              }
            }, (playRes) => {
              let playBody = '';
              playRes.on('data', c => playBody += c);
              playRes.on('end', () => {
                try {
                  const playData = JSON.parse(playBody);
                  if (playData.url) {
                    const parsedGameUrl = new URL(playData.url);
                    const fv = {};
                    for (const [k, v] of parsedGameUrl.searchParams.entries()) {
                      if (k === 'config') {
                        fv[k] = `http://localhost:${HTTP_PORT}/host/flash1.gunnyhoiuc.com:88/config.xml${v.includes('?') ? v.substring(v.indexOf('?')) : ''}`;
                      } else {
                        fv[k] = v;
                      }
                    }
                    lastDetectedGameServer = { host: '103.92.27.133', port: 9200 };
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({
                      ok: true,
                      swfUrl: `http://localhost:${HTTP_PORT}/host/flash1.gunnyhoiuc.com:88/Loading.swf`,
                      proxiedSwfUrl: `http://localhost:${HTTP_PORT}/host/flash1.gunnyhoiuc.com:88/Loading.swf`,
                      flashvars: fv,
                      baseUrl: `http://localhost:${HTTP_PORT}/host/flash1.gunnyhoiuc.com:88/`,
                      serverHost: '103.92.27.133',
                      serverPort: 9200,
                      message: `Đã kết nối thành công Gunny Hồi Ức (S3 - Gà Vàng) cho tài khoản ${user}!`
                    }));
                  } else {
                    res.writeHead(400, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ ok: false, error: 'Không lấy được link vào game từ server.' }));
                  }
                } catch(e) {
                  res.writeHead(500, { 'Content-Type': 'application/json' });
                  res.end(JSON.stringify({ ok: false, error: e.message }));
                }
              });
            });
            playReq.write(playPayload);
            playReq.end();
          } catch(e) {
            res.writeHead(500, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ ok: false, error: e.message }));
          }
        });
      });
      loginReq.write(loginPayload);
      loginReq.end();
    } catch(e) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
    return;
  }

  // Native Adobe Flash Player 32 Standalone Runner: /launch-native-flash?url=<encoded>
  if (pathname === '/launch-native-flash') {
    const rawGameUrl = reqUrl.searchParams.get('url');
    if (!rawGameUrl) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: 'Tham số url là bắt buộc.' }));
      return;
    }

    try {
      console.log(`[Bridge] Launching Native Flash Player 32 with URL: ${rawGameUrl}`);
      const flashAppPath = path.join(__dirname, '..', 'runtime', 'flash', 'Flash Player.app');
      
      const child = spawn('open', ['-a', flashAppPath, '--args', rawGameUrl], {
        detached: true,
        stdio: 'ignore'
      });
      child.unref();

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        ok: true,
        message: 'Đã mở Adobe Flash Player 32 Standalone thành công!',
        url: rawGameUrl
      }));
    } catch(err) {
      console.error('[Bridge] Error launching native Flash Player:', err);
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: err.message }));
    }
    return;
  }

  // Universal Smart URL Sniffer / Auto-Detector: /sniff-game-url?url=<encoded>
  if (pathname === '/sniff-game-url') {
    const rawUrl = reqUrl.searchParams.get('url');
    if (!rawUrl) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: 'Tham số url là bắt buộc.' }));
      return;
    }

    try {
      console.log(`[Bridge] Sniffing game URL: ${rawUrl}`);
      const { response: pageRes } = await fetchWithRedirects(rawUrl);
      const html = await readTextResponse(pageRes);

      // 1. Extract SWF Path from Flash portals (Newgrounds, Kongregate, ArmorGames, Gunny...)
      let swf = '';
      const mSwf = html.match(/swf\s*:\s*["']([^"']+\.swf(\?[^"']*)?)["']/i) ||
                    html.match(/swfPath\s*=\s*["']([^"']+)["']/i) || 
                    html.match(/["'](https?:\/\/[^"'\s]+\.swf(\?[^"'\s]*)?)["']/i) ||
                    html.match(/src\s*=\s*["']([^"']+\.swf[^"']*)["']/i) ||
                    html.match(/(https?:\/\/[^"'\s]+\.swf)/i);
      if (mSwf) {
        swf = mSwf[1];
      } else {
        // Check for HTML5 / WebGL embed (e.g. Newgrounds game_drop, itch.io, crazygames)
        const mHtml5 = html.match(/(https?[:\/\\]+uploads\.ungrounded\.net[:\/\\]+alternate[:\/\\]+[^"'\s>]+)/i) ||
                      html.match(/src=\\?"(https?:\/\/uploads\.ungrounded\.net\/[^"'\s>]+)\\?"/i) ||
                      html.match(/<iframe[^>]*id=["']game_drop["'][^>]*src=["']([^"']+)["']/i) ||
                      html.match(/<iframe[^>]*src=["'](https?:\/\/(?!.*passport)[^"']+)["']/i);
        if (mHtml5) {
          let embedUrl = mHtml5[1].replace(/\\/g, '').replace(/&amp;/g, '&').replace(/"/g, '');
          if (embedUrl.startsWith('//')) embedUrl = 'https:' + embedUrl;
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({
            ok: true,
            type: 'html5',
            gameUrl: embedUrl,
            domain: new URL(rawUrl).hostname,
            message: 'Đã tự động phát hiện Web Game HTML5/WebGL!'
          }));
          return;
        }

        // Return error if no Flash (.swf) or valid HTML5 game embed is found
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          ok: false,
          error: 'Không tìm thấy tệp Flash (.swf) hoặc Web Game nhúng hợp lệ trên trang này. Vui lòng nhập link trực tiếp file .swf hoặc chọn từ tab Presets.'
        }));
        return;
      }

      // 2. Extract Flashvars
      let fv = {};
      const mFvObj = html.match(/flashvars\s*=\s*({[\s\S]*?});/i);
      if (mFvObj) {
        try { eval('fv = ' + mFvObj[1]); } catch(e){}
      }
      if (!fv || Object.keys(fv).length === 0) {
        const mFvStr = html.match(/flashvars["'\s]*[:=]["'\s]*([a-zA-Z0-9_=&%\/:.\-]+)/i);
        if (mFvStr) {
          const sp = new URLSearchParams(mFvStr[1].replace(/&amp;/g, '&'));
          for (const pair of sp.entries()) fv[pair[0]] = pair[1];
        }
      }

      const parsedSwf = new URL(swf, rawUrl);
      const cleanSwf = parsedSwf.href.replace(/([^:])\/\//g, '$1/');
      const proxiedSwf = `http://localhost:${HTTP_PORT}/host/${parsedSwf.host}${parsedSwf.pathname}`;
      const baseFolder = parsedSwf.pathname.substring(0, parsedSwf.pathname.lastIndexOf('/') + 1);
      const baseUrl = `http://localhost:${HTTP_PORT}/host/${parsedSwf.host}${baseFolder}`;

      if (fv.config) {
        try {
          const parsedConfig = new URL(fv.config, rawUrl);
          fv.config = `http://localhost:${HTTP_PORT}/host/${parsedConfig.host}${parsedConfig.pathname}`;
        } catch(e) {
          fv.config = `http://localhost:${HTTP_PORT}/proxy?url=${encodeURIComponent(fv.config)}`;
        }
      }

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        ok: true,
        swfUrl: cleanSwf,
        proxiedSwfUrl: proxiedSwf,
        flashvars: fv,
        baseUrl: baseUrl,
        domain: parsedSwf.host,
        message: `Đã tự động phân tích và trích xuất cấu hình game từ ${parsedSwf.host}!`
      }));
      return;
    } catch(err) {
      console.error('[Bridge] Error sniffing game URL:', err);
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: false, error: `Lỗi kết nối tới URL: ${err.message}` }));
      return;
    }
  }

  // Universal Host-based Path Proxy Routing: /host/<domain>/<path>?<query>
  let targetUrl = null;

  if (pathname.startsWith('/host/')) {
    const afterHost = pathname.substring('/host/'.length);
    const slashIdx = afterHost.indexOf('/');
    const targetHost = slashIdx !== -1 ? afterHost.substring(0, slashIdx) : afterHost;
    const targetPath = slashIdx !== -1 ? afterHost.substring(slashIdx) : '/';
    const protocol = (targetHost.includes('127.0.0.1') || targetHost.includes('localhost') || targetHost.startsWith('flash') || targetHost.startsWith('quest')) ? 'http' : 'https';
    targetUrl = `${protocol}://${targetHost}${targetPath}${reqUrl.search}`;
  } else if (pathname.startsWith('/vcdn/')) {
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

  // Handle 404 fallbacks for private server legacy trainer files
  if (pathname.endsWith('/tutorial.swf')) {
    targetUrl = targetUrl ? targetUrl.replace(/\/tutorial\.swf/i, '/ui/spain/swf/Trainer.swf') : 'https://123gn.net/flash3/ui/spain/swf/Trainer.swf';
  }

  if (targetUrl) {
    try {
      const { response: proxyRes, finalUrl } = await fetchWithRedirects(targetUrl);
      
      // Automatically capture active game server IP/Port from ServerList.ashx
      if (pathname.endsWith('/ServerList.ashx') || pathname.endsWith('/LoginServerList.ashx')) {
        let serverListXml = await readTextResponse(proxyRes);
        if (targetUrl.includes('gunnyhoiuc.com')) {
          lastDetectedGameServer = { host: '103.92.27.133', port: 9200 };
          serverListXml = serverListXml.replace(/Port=["'][0-9]+["']/gi, 'Port="9200"');
          console.log(`[Bridge] 🎯 Remapped Gunny Hồi Ức game server to TCP socket 103.92.27.133:9200`);
        } else {
          const ipMatch = /IP=["']([^"']+)["']\s+Port=["']([0-9]+)["']/i.exec(serverListXml);
          if (ipMatch) {
            lastDetectedGameServer = { host: ipMatch[1], port: parseInt(ipMatch[2], 10) };
            console.log(`[Bridge] 🎯 Dynamically detected active game server TCP socket: ${lastDetectedGameServer.host}:${lastDetectedGameServer.port}`);
          }
        }
        res.writeHead(200, {
          'Content-Type': 'application/xml; charset=utf-8',
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Headers': '*',
          'Cache-Control': 'no-cache'
        });
        res.end(serverListXml);
        return;
      }

      // ONLY rewrite plain text client configuration XML files (e.g. config.xml, config3.xml)
      // NEVER touch game template XMLs like PetConfigInfo.xml, BombConfig.xml, ServerConfig.xml
      const isClientConfigXml = /\/config[0-9]*\.xml/i.test(pathname);

      if (isClientConfigXml) {
        const xmlContent = await readTextResponse(proxyRes);

        const trainerPath = (targetUrl && targetUrl.includes('gunnyhoiuc.com')) ? 'ui/vietnam/swf/Trainer.swf' : 'ui/spain/swf/Trainer.swf';
        let rewrittenXml = xmlContent
          .replace(/<TRAINER_PATH\s+value=["']tutorial\.swf["']\s*\/>/gi, `<TRAINER_PATH value="${trainerPath}" />`)
          .replace(
            /value=["'](https?:\/\/([^"'\/]+)([^"']*))["']/gi,
            (match, fullUrl, host, restPath) => {
              if (fullUrl.startsWith(`http://localhost:${HTTP_PORT}`)) return match;
              return `value="http://localhost:${HTTP_PORT}/host/${host}${restPath}"`;
            }
          );

        res.writeHead(200, {
          'Content-Type': 'application/xml; charset=utf-8',
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Headers': '*',
          'Cache-Control': 'no-cache',
          'X-Rewritten-By': 'Universal-Host-Config-Proxy'
        });
        res.end(rewrittenXml);
        return;
      }

      // Stream ALL binary assets and data XML files untouched
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
  let targetHost = reqUrl.searchParams.get('host');
  let targetPort = parseInt(reqUrl.searchParams.get('port'), 10);

  // Intelligent fallback to active game server
  if (targetHost === '103.92.27.133' || (targetHost && targetHost.includes('gunnyhoiuc.com'))) {
    targetHost = '103.92.27.133';
    if (targetPort === 9131 || !targetPort || isNaN(targetPort)) {
      targetPort = 9200;
    }
  } else if (!targetHost || targetHost === '127.0.0.1' || targetHost === 'localhost') {
    targetHost = lastDetectedGameServer.host;
  }

  if (!targetPort || isNaN(targetPort) || (targetPort === 9200 && lastDetectedGameServer.port !== 9200)) {
    targetPort = lastDetectedGameServer.port;
  }

  console.log(`[Bridge] 🔌 New Flash Socket client connected. Forwarding to TCP ${targetHost}:${targetPort}`);

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
