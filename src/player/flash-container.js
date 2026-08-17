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
      warnOnUnsupportedContent: false,
      logLevel: 'warn',
      quality: this.options.quality,
      wmode: this.options.wmode,
      allowScriptAccess: this.options.allowScriptAccess,
      socketProxy: [
        {
          host: '127.0.0.1',
          port: 9200,
          proxyUrl: this.options.bridgeWsUrl
        },
        {
          host: 'localhost',
          port: 9200,
          proxyUrl: this.options.bridgeWsUrl
        }
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
        wmode: this.options.wmode,
        quality: this.options.quality,
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
      case '4:3':
        this.playerInstance.style.aspectRatio = '4 / 3';
        this.playerInstance.style.maxHeight = '100%';
        this.playerInstance.style.maxWidth = 'calc(100vh * (4/3))';
        break;
      case '16:9':
        this.playerInstance.style.aspectRatio = '16 / 9';
        this.playerInstance.style.maxHeight = '100%';
        this.playerInstance.style.maxWidth = 'calc(100vh * (16/9))';
        break;
      case 'original':
        this.playerInstance.style.width = 'auto';
        this.playerInstance.style.height = 'auto';
        break;
      case 'stretch':
        this.playerInstance.style.width = '100%';
        this.playerInstance.style.height = '100%';
        this.playerInstance.style.objectFit = 'fill';
        break;
      case 'fit':
      default:
        this.playerInstance.style.width = '100%';
        this.playerInstance.style.height = '100%';
        this.playerInstance.style.objectFit = 'contain';
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
    if (this.playerInstance) {
      try {
        this.playerInstance.remove();
      } catch (e) {}
      this.playerInstance = null;
    }
    this.isLoaded = false;
  }
}
