/**
 * Flash Runtime Container & Ruffle WASM Engine Integration
 * Universal Agent OS - Web Flash Player
 */

export class FlashContainer {
  constructor(containerElement, options = {}) {
    this.container = containerElement;
    this.options = {
      scaleMode: 'fit', // fit | original | 4:3 | 16:9 | stretch
      quality: 'high',
      wmode: 'direct',
      allowScriptAccess: true,
      volume: 1.0,
      bridgeWsUrl: 'ws://localhost:8080',
      ...options
    };

    this.ruffle = null;
    this.playerInstance = null;
    this.currentSource = null;
    this.currentOptions = {};
    this.isLoaded = false;
    this.fps = 60;
    this.frameCount = 0;
    this.lastFpsTimestamp = performance.now();
    this.fpsTimer = null;

    this.events = {
      loadStart: [],
      loadSuccess: [],
      loadError: [],
      fpsUpdate: [],
      stateChange: []
    };
  }

  on(event, handler) {
    if (this.events[event]) {
      this.events[event].push(handler);
    }
  }

  emit(event, data) {
    if (this.events[event]) {
      this.events[event].forEach((fn) => fn(data));
    }
  }

  async initRuffle() {
    if (this.ruffle) return this.ruffle;

    // Configure window.RufflePlayer global config
    window.RufflePlayer = window.RufflePlayer || {};
    window.RufflePlayer.config = {
      publicPath: '/ruffle/',
      polyfills: true,
      autoplay: 'on',
      unmuteOverlay: 'visible',
      letterbox: 'on',
      openUrlMode: 'deny',
      preferredRenderer: 'wgpu-webgl',
      deviceFontRenderer: 'canvas',
      warnOnUnsupportedContent: false,
      logLevel: 'warn',
      quality: 'high',
      wmode: 'transparent',
      allowScriptAccess: this.options.allowScriptAccess,
      fontSources: [
        '/fonts/Arial.ttf',
        '/fonts/Arial-Bold.ttf',
        '/fonts/Tahoma.ttf',
        '/fonts/Tahoma-Bold.ttf'
      ],
      defaultFonts: {
        sans: ['Arial', 'Tahoma', 'Inter', 'sans-serif'],
        sansSerif: ['Arial', 'Tahoma', 'Inter', 'sans-serif'],
        serif: ['Times New Roman', 'serif'],
        typewriter: ['Courier New', 'monospace']
      },
      socketProxy: [
        // Gun321 Game Server
        { host: '103.92.25.226', port: 30303, proxyUrl: this.options.bridgeWsUrl },
        { host: '103.92.25.226', port: 30203, proxyUrl: this.options.bridgeWsUrl },
        { host: '103.92.25.226', port: 9200, proxyUrl: this.options.bridgeWsUrl },
        { host: '139.99.69.14', port: 30133, proxyUrl: this.options.bridgeWsUrl },
        { host: 'gun321.vip', port: 30303, proxyUrl: this.options.bridgeWsUrl },
        { host: 'gun321.vip', port: 30203, proxyUrl: this.options.bridgeWsUrl },

        // 123gn.net Game Server
        { host: '15.235.193.106', port: 25565, proxyUrl: this.options.bridgeWsUrl },
        { host: '15.235.193.106', port: 9200, proxyUrl: this.options.bridgeWsUrl },
        { host: '15.235.193.106', port: 9201, proxyUrl: this.options.bridgeWsUrl },
        { host: '15.235.193.106', port: 9208, proxyUrl: this.options.bridgeWsUrl },
        { host: '123gn.net', port: 25565, proxyUrl: this.options.bridgeWsUrl },
        { host: '123gn.net', port: 9200, proxyUrl: this.options.bridgeWsUrl },
        { host: '123gn.net', port: 9201, proxyUrl: this.options.bridgeWsUrl },

        // Zing Gunny Game Servers
        { host: 's737.gn.zing.vn', port: 9200, proxyUrl: this.options.bridgeWsUrl },
        { host: 's737.gn.zing.vn', port: 9201, proxyUrl: this.options.bridgeWsUrl },
        { host: 's737.gn.zing.vn', port: 9208, proxyUrl: this.options.bridgeWsUrl },
        { host: 's737.gn.zing.vn', port: 25565, proxyUrl: this.options.bridgeWsUrl },
        { host: 'quest737.gn.zing.vn', port: 9200, proxyUrl: this.options.bridgeWsUrl },
        { host: 'quest737.gn.zing.vn', port: 9201, proxyUrl: this.options.bridgeWsUrl },
        { host: 'gunny.vcdn.vn', port: 9200, proxyUrl: this.options.bridgeWsUrl },

        // Gunny Hồi Ức Game Server
        { host: '103.92.27.133', port: 9131, proxyUrl: this.options.bridgeWsUrl },
        { host: '103.92.27.133', port: 9200, proxyUrl: this.options.bridgeWsUrl },
        { host: '103.92.27.133', port: 9300, proxyUrl: this.options.bridgeWsUrl },
        { host: '103.92.27.133', port: 25565, proxyUrl: this.options.bridgeWsUrl },
        { host: 'gunnyhoiuc.com', port: 9131, proxyUrl: this.options.bridgeWsUrl },
        { host: 'gunnyhoiuc.com', port: 9200, proxyUrl: this.options.bridgeWsUrl },
        { host: 'gunnyhoiuc.com', port: 9300, proxyUrl: this.options.bridgeWsUrl },
        { host: 'flash1.gunnyhoiuc.com', port: 9131, proxyUrl: this.options.bridgeWsUrl },
        { host: 'flash1.gunnyhoiuc.com', port: 9200, proxyUrl: this.options.bridgeWsUrl },
        { host: 'quest1.gunnyhoiuc.com', port: 9131, proxyUrl: this.options.bridgeWsUrl },
        { host: 'quest1.gunnyhoiuc.com', port: 9200, proxyUrl: this.options.bridgeWsUrl },
        { host: 'resource.gunnyhoiuc.com', port: 9131, proxyUrl: this.options.bridgeWsUrl },
        { host: 'resource.gunnyhoiuc.com', port: 9200, proxyUrl: this.options.bridgeWsUrl },

        // Local Dev & Generic Servers
        { host: '127.0.0.1', port: 9131, proxyUrl: this.options.bridgeWsUrl },
        { host: '127.0.0.1', port: 9200, proxyUrl: this.options.bridgeWsUrl },
        { host: '127.0.0.1', port: 9201, proxyUrl: this.options.bridgeWsUrl },
        { host: '127.0.0.1', port: 25565, proxyUrl: this.options.bridgeWsUrl },
        { host: 'localhost', port: 9131, proxyUrl: this.options.bridgeWsUrl },
        { host: 'localhost', port: 9200, proxyUrl: this.options.bridgeWsUrl },
        { host: 'localhost', port: 9201, proxyUrl: this.options.bridgeWsUrl },
        { host: 'localhost', port: 25565, proxyUrl: this.options.bridgeWsUrl }
      ]
    };

    // Load ruffle.js script if not loaded
    if (!window.RufflePlayer.newest) {
      await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = '/ruffle/ruffle.js';
        script.async = true;
        script.onload = resolve;
        script.onerror = () => reject(new Error('Failed to load /ruffle/ruffle.js'));
        document.head.appendChild(script);
      });
    }

    this.ruffle = window.RufflePlayer.newest();
    console.log('[FlashContainer] Ruffle WASM Engine initialized successfully.');
    return this.ruffle;
  }

  async loadSwf(source, customConfig = {}) {
    this.emit('loadStart', { source });

    try {
      await this.initRuffle();

      // Clean up previous instance
      this.destroyCurrentPlayer();

      // Create new Ruffle player instance
      this.playerInstance = this.ruffle.createPlayer();
      this.playerInstance.id = 'flash-player-instance';
      this.playerInstance.className = 'w-full h-full flash-canvas-element';

      // Set scale mode class on container
      this.applyScaleMode(this.options.scaleMode);

      // Append to DOM
      this.container.innerHTML = '';
      this.container.appendChild(this.playerInstance);

      this.currentSource = source;
      this.currentOptions = customConfig;

      const loadConfig = {
        parameters: customConfig.flashvars || {},
        allowScriptAccess: true,
        openUrlMode: 'deny',
        deviceFontRenderer: 'canvas',
        socketProxy: (window.RufflePlayer && window.RufflePlayer.config && window.RufflePlayer.config.socketProxy) ? window.RufflePlayer.config.socketProxy : [],
        wmode: 'transparent',
        quality: 'high',
        autoplay: 'on',
        ...customConfig
      };

      if (typeof source === 'string') {
        loadConfig.url = source;
        await this.playerInstance.load(loadConfig);
      } else if (source instanceof ArrayBuffer || source instanceof Uint8Array) {
        loadConfig.data = source;
        await this.playerInstance.load(loadConfig);
      } else if (source instanceof Blob || source instanceof File) {
        const buffer = await source.arrayBuffer();
        loadConfig.data = buffer;
        await this.playerInstance.load(loadConfig);
      } else {
        throw new Error('Unsupported SWF source type');
      }

      this.isLoaded = true;
      this.startFpsTracker();
      this.setVolume(this.options.volume);

      this.emit('loadSuccess', { source, config: loadConfig });
      this.emit('stateChange', { status: 'running', source });

      return true;
    } catch (err) {
      console.error('[FlashContainer] Error loading SWF:', err);
      this.emit('loadError', { error: err.message, source });
      this.emit('stateChange', { status: 'error', error: err.message });
      throw err;
    }
  }

  loadHtml5Game(url) {
    this.emit('loadStart', { source: url, type: 'html5' });
    this.destroyCurrentPlayer();

    const iframe = document.createElement('iframe');
    iframe.id = 'html5-game-instance';
    iframe.className = 'w-full h-full flash-canvas-element';
    iframe.style.border = 'none';
    iframe.style.width = '100%';
    iframe.style.height = '100%';
    iframe.style.borderRadius = '8px';
    iframe.src = url;
    iframe.allow = 'autoplay; fullscreen; microphone; camera; gamepad; clipboard-read; clipboard-write';
    iframe.setAttribute('allowfullscreen', 'true');

    this.container.innerHTML = '';
    this.container.appendChild(iframe);
    this.playerInstance = iframe;
    this.currentSource = url;
    this.isLoaded = true;

    this.applyScaleMode(this.options.scaleMode);
    this.startFpsTracker();

    this.emit('loadSuccess', { source: url, type: 'html5' });
    this.emit('stateChange', { status: 'running', source: url, type: 'html5' });
    return true;
  }

  applyScaleMode(mode) {
    this.options.scaleMode = mode;
    this.container.dataset.scaleMode = mode;

    if (!this.playerInstance) return;

    // Reset styles
    this.playerInstance.style.aspectRatio = '';
    this.playerInstance.style.maxWidth = '';
    this.playerInstance.style.maxHeight = '';
    this.playerInstance.style.width = '100%';
    this.playerInstance.style.height = '100%';

    switch (mode) {
      case '5:3':
      case 'gunny':
        this.playerInstance.style.aspectRatio = '5 / 3';
        this.playerInstance.style.width = 'auto';
        this.playerInstance.style.height = '100%';
        this.playerInstance.style.maxWidth = '100%';
        this.playerInstance.style.maxHeight = '100%';
        break;
      case '4:3':
        this.playerInstance.style.aspectRatio = '4 / 3';
        this.playerInstance.style.width = 'auto';
        this.playerInstance.style.height = '100%';
        this.playerInstance.style.maxWidth = '100%';
        this.playerInstance.style.maxHeight = '100%';
        break;
      case '16:9':
        this.playerInstance.style.aspectRatio = '16 / 9';
        this.playerInstance.style.width = 'auto';
        this.playerInstance.style.height = '100%';
        this.playerInstance.style.maxWidth = '100%';
        this.playerInstance.style.maxHeight = '100%';
        break;
      case 'original':
        this.playerInstance.style.width = '1000px';
        this.playerInstance.style.height = '600px';
        this.playerInstance.style.maxWidth = '100%';
        this.playerInstance.style.maxHeight = '100%';
        break;
      case 'stretch':
        this.playerInstance.style.width = '100%';
        this.playerInstance.style.height = '100%';
        this.playerInstance.style.objectFit = 'fill';
        break;
      case 'fit':
      default:
        this.playerInstance.style.aspectRatio = '5 / 3';
        this.playerInstance.style.width = 'auto';
        this.playerInstance.style.height = '100%';
        this.playerInstance.style.maxWidth = '100%';
        this.playerInstance.style.maxHeight = '100%';
        break;
    }
  }

  setVolume(volume) {
    this.options.volume = Math.max(0, Math.min(1, volume));
    if (this.playerInstance && typeof this.playerInstance.setVolume === 'function') {
      try {
        this.playerInstance.setVolume(this.options.volume);
      } catch (e) {
        console.warn('[FlashContainer] setVolume warning:', e);
      }
    }
  }

  restart() {
    if (this.currentSource) {
      return this.loadSwf(this.currentSource, this.currentOptions);
    }
  }

  toggleFullscreen() {
    if (!document.fullscreenElement) {
      if (this.container.requestFullscreen) {
        this.container.requestFullscreen();
      } else if (this.container.webkitRequestFullscreen) {
        this.container.webkitRequestFullscreen();
      }
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
      }
    }
  }

  captureScreenshot() {
    if (!this.playerInstance) return null;
    try {
      const canvas = this.playerInstance.querySelector('canvas');
      if (!canvas) return null;
      return canvas.toDataURL('image/png');
    } catch (e) {
      console.error('[FlashContainer] Screenshot capture failed:', e);
      return null;
    }
  }

  startFpsTracker() {
    this.stopFpsTracker();
    let frames = 0;
    let lastTime = performance.now();

    const loop = (now) => {
      frames++;
      if (now - lastTime >= 1000) {
        this.fps = Math.round((frames * 1000) / (now - lastTime));
        this.emit('fpsUpdate', { fps: this.fps });
        frames = 0;
        lastTime = now;
      }
      this.fpsTimer = requestAnimationFrame(loop);
    };
    this.fpsTimer = requestAnimationFrame(loop);
  }

  stopFpsTracker() {
    if (this.fpsTimer) {
      cancelAnimationFrame(this.fpsTimer);
      this.fpsTimer = null;
    }
  }

  destroyCurrentPlayer() {
    this.stopFpsTracker();
    if (this.container) {
      this.container.innerHTML = '';
    }
    if (this.playerInstance) {
      try {
        if (typeof this.playerInstance.remove === 'function') {
          this.playerInstance.remove();
        }
      } catch (e) {}
      this.playerInstance = null;
    }
    this.isLoaded = false;
  }
}
