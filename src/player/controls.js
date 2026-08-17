/**
 * Player UI Controls & Event Bindings
 * Universal Agent OS - Web Flash Player
 */

export class PlayerControls {
  constructor(flashContainer, bridgeClient) {
    this.player = flashContainer;
    this.bridge = bridgeClient;

    this.initDOMElements();
    this.bindEvents();
  }

  initDOMElements() {
    this.btnFullscreen = document.getElementById('btn-fullscreen');
    this.selectScale = document.getElementById('select-scale');
    this.sliderVolume = document.getElementById('slider-volume');
    this.btnMute = document.getElementById('btn-mute');
    this.btnScreenshot = document.getElementById('btn-screenshot');
    this.btnRestart = document.getElementById('btn-restart');
    this.fpsCounter = document.getElementById('fps-counter');

    this.dropzone = document.getElementById('dropzone');
    this.fileInput = document.getElementById('file-input');
    this.emptyState = document.getElementById('empty-state');
    this.flashContainerEl = document.getElementById('flash-container');

    this.tabButtons = document.querySelectorAll('.tab-btn');
    this.tabContents = document.querySelectorAll('.tab-content');

    this.inputSwfUrl = document.getElementById('input-swf-url');
    this.checkCorsProxy = document.getElementById('check-use-cors-proxy');
    this.btnLoadUrl = document.getElementById('btn-load-url');

    this.inputGunnyHost = document.getElementById('input-gunny-host');
    this.inputGunnyPort = document.getElementById('input-gunny-port');
    this.inputGunnyResource = document.getElementById('input-gunny-resource');
    this.btnLaunchGunny = document.getElementById('btn-launch-gunny');
    this.bridgeConsole = document.getElementById('bridge-console');

    this.inputFlashvars = document.getElementById('input-flashvars');
    this.selectQuality = document.getElementById('select-quality');
    this.btnApplyVars = document.getElementById('btn-apply-vars');

    this.toastContainer = document.getElementById('toast-container');
  }

  bindEvents() {
    // 1. Fullscreen Toggle
    this.btnFullscreen.addEventListener('click', () => {
      this.player.toggleFullscreen();
    });

    // 2. Scale Mode Change
    this.selectScale.addEventListener('change', (e) => {
      this.player.applyScaleMode(e.target.value);
      this.showToast(`Đã đổi tỷ lệ khung hình: ${e.target.options[e.target.selectedIndex].text}`);
    });

    // 3. Volume & Mute
    this.sliderVolume.addEventListener('input', (e) => {
      const vol = parseFloat(e.target.value);
      this.player.setVolume(vol);
    });

    let isMuted = false;
    let prevVolume = 1;
    this.btnMute.addEventListener('click', () => {
      if (!isMuted) {
        prevVolume = parseFloat(this.sliderVolume.value) || 1;
        this.sliderVolume.value = 0;
        this.player.setVolume(0);
        isMuted = true;
        this.showToast('Đã tắt âm thanh');
      } else {
        this.sliderVolume.value = prevVolume;
        this.player.setVolume(prevVolume);
        isMuted = false;
        this.showToast('Đã bật lại âm thanh');
      }
    });

    // 4. Screenshot Capture
    this.btnScreenshot.addEventListener('click', () => {
      const dataUrl = this.player.captureScreenshot();
      if (dataUrl) {
        const a = document.createElement('a');
        a.href = dataUrl;
        a.download = `flash_screenshot_${Date.now()}.png`;
        a.click();
        this.showToast('Đã lưu ảnh chụp màn hình game!');
      } else {
        this.showToast('Chưa thể chụp màn hình (Game chưa nạp)');
      }
    });

    // 5. Restart
    this.btnRestart.addEventListener('click', () => {
      if (this.player.isLoaded) {
        this.player.restart();
        this.showToast('Đang nạp lại Game...');
      }
    });

    // 6. Tabs Switcher
    this.tabButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        this.tabButtons.forEach((b) => b.classList.remove('active'));
        this.tabContents.forEach((c) => c.classList.remove('active'));

        btn.classList.add('active');
        const targetTab = document.getElementById(btn.dataset.tab);
        if (targetTab) targetTab.classList.add('active');
      });
    });

    // 7. Drag & Drop File Upload
    this.dropzone.addEventListener('click', () => this.fileInput.click());

    this.dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      this.dropzone.classList.add('dragover');
    });

    this.dropzone.addEventListener('dragleave', () => {
      this.dropzone.classList.remove('dragover');
    });

    this.dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      this.dropzone.classList.remove('dragover');
      const files = e.dataTransfer.files;
      if (files.length > 0 && files[0].name.toLowerCase().endsWith('.swf')) {
        this.loadLocalFile(files[0]);
      } else {
        this.showToast('Vui lòng chọn đúng tệp có định dạng .swf!');
      }
    });

    this.fileInput.addEventListener('change', (e) => {
      if (e.target.files && e.target.files.length > 0) {
        this.loadLocalFile(e.target.files[0]);
      }
    });

    // 8. Direct URL Loader
    this.btnLoadUrl.addEventListener('click', () => {
      const rawUrl = this.inputSwfUrl.value.trim();
      if (!rawUrl) {
        this.showToast('Vui lòng nhập đường dẫn URL của file SWF!');
        return;
      }

      let finalUrl = rawUrl;
      if (this.checkCorsProxy.checked) {
        finalUrl = this.bridge.getProxiedUrl(rawUrl);
      }

      this.showToast(`Đang tải SWF từ URL...`);
      this.runGame(finalUrl, { flashvars: this.getParsedFlashvars() });
    });

    // 9. Gunny Launch Button
    this.btnLaunchGunny.addEventListener('click', () => {
      const host = this.inputGunnyHost.value.trim();
      const port = this.inputGunnyPort.value.trim();
      const resource = this.inputGunnyResource.value.trim();

      this.logBridge(`[Gunny] Chuẩn bị khởi chạy kết nối TCP -> ${host}:${port}`);
      this.logBridge(`[Gunny] Tài nguyên: ${resource}`);

      const loadingSwf = `${resource}Loading.swf`;
      const proxiedLoadingSwf = this.bridge.getProxiedUrl(loadingSwf);

      const gunnyVars = {
        user: 'admin',
        key: 'gunny_key_demo',
        config: `${resource}config.xml`,
        v: '1000'
      };

      this.showToast(`Đang kết nối Server Gunny (${host}:${port})...`);
      this.runGame(proxiedLoadingSwf, { flashvars: gunnyVars });
    });

    // 10. FPS Tracker Event
    this.player.on('fpsUpdate', ({ fps }) => {
      if (this.fpsCounter) {
        this.fpsCounter.textContent = `${fps} FPS`;
      }
    });
  }

  loadLocalFile(file) {
    this.showToast(`Đang nạp file: ${file.name}`);
    this.runGame(file, { flashvars: this.getParsedFlashvars() });
  }

  async runGame(source, config = {}) {
    this.emptyState.style.display = 'none';
    this.flashContainerEl.style.display = 'flex';

    try {
      await this.player.loadSwf(source, config);
      this.showToast('Game đã được tải thành công!');
    } catch (e) {
      this.showToast(`Lỗi khi nạp game: ${e.message}`);
    }
  }

  getParsedFlashvars() {
    const raw = this.inputFlashvars.value.trim();
    if (!raw) return {};
    try {
      return JSON.parse(raw);
    } catch (e) {
      // Parse as query string format: a=1&b=2
      const params = new URLSearchParams(raw);
      const obj = {};
      for (const [key, value] of params.entries()) {
        obj[key] = value;
      }
      return obj;
    }
  }

  logBridge(message, type = 'info') {
    if (!this.bridgeConsole) return;
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;
    const time = new Date().toLocaleTimeString();
    entry.textContent = `[${time}] ${message}`;
    this.bridgeConsole.appendChild(entry);
    this.bridgeConsole.scrollTop = this.bridgeConsole.scrollHeight;
  }

  showToast(message) {
    if (!this.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="var(--neon-cyan)" stroke-width="2">
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="12" y1="16" x2="12" y2="12"></line>
        <line x1="12" y1="8" x2="12.01" y2="8"></line>
      </svg>
      <span>${message}</span>
    `;
    this.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.transition = 'all 0.3s';
      setTimeout(() => toast.remove(), 300);
    }, 3200);
  }
}
