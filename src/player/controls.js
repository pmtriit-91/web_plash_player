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
    this.btnSyncZing = document.getElementById('btn-sync-zing');
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

    // 8. Direct URL Loader with Smart Inspector
    this.btnLoadUrl.addEventListener('click', async () => {
      const rawUrl = this.inputSwfUrl.value.trim();
      if (!rawUrl) {
        this.showToast('Vui lòng nhập đường dẫn URL của file SWF hoặc trang game!');
        return;
      }

      this.btnLoadUrl.disabled = true;
      this.btnLoadUrl.innerHTML = '<span>Đang phân tích URL...</span>';

      try {
        // Inspect URL via Bridge Inspector
        const inspectRes = await fetch(`http://localhost:8081/inspect-url?url=${encodeURIComponent(rawUrl)}`);
        if (inspectRes.ok) {
          const info = await inspectRes.json();

          if (info.type === 'swf') {
            this.showToast('Đã phát hiện tệp SWF trực tiếp. Đang tải game...');
            const targetUrl = this.checkCorsProxy.checked ? this.bridge.getProxiedUrl(info.swfUrl) : info.swfUrl;
            await this.runGame(targetUrl, { flashvars: this.getParsedFlashvars() });
          } else if (info.type === 'html_with_flash') {
            this.showToast(`Phát hiện Flash game trong trang! Đang nạp: ${info.swfUrl.split('/').pop()}`);
            if (info.flashvars && Object.keys(info.flashvars).length > 0) {
              this.inputFlashvars.value = JSON.stringify(info.flashvars, null, 2);
            }
            const targetUrl = this.checkCorsProxy.checked ? this.bridge.getProxiedUrl(info.swfUrl) : info.swfUrl;
            await this.runGame(targetUrl, { flashvars: info.flashvars || this.getParsedFlashvars() });
          } else if (info.type === 'login_required') {
            this.showToast(`⚠️ Yêu cầu Đăng nhập: ${info.message}`, 6000);
            alert(`⚠️ CẢNH BÁO XÁC THỰC (LOGIN REQUIRED):\n\nĐường dẫn "${rawUrl}" là trang xác thực/đăng nhập của Zing ID (yêu cầu Cookie đăng nhập của tài khoản).\n\n👉 Để chơi Gunny Zing trên Web Player:\n1. Mở game trên trình duyệt và đăng nhập tài khoản Zing.\n2. Nhấn F12 (Network) -> Tìm tệp "Loading.swf" và copy đường link trực tiếp cùng Flashvars (user, key, v, config).\n3. Dán link Loading.swf vào Web Flash Player để chơi mượt mà!`);
          } else {
            this.showToast(`⚠️ ${info.message || 'Không tìm thấy tệp Flash (.swf)'}`, 5000);
          }
        } else {
          // Fallback direct load
          const targetUrl = this.checkCorsProxy.checked ? this.bridge.getProxiedUrl(rawUrl) : rawUrl;
          await this.runGame(targetUrl, { flashvars: this.getParsedFlashvars() });
        }
      } catch (err) {
        this.showToast(`Lỗi phân tích link: ${err.message}`);
      } finally {
        this.btnLoadUrl.disabled = false;
        this.btnLoadUrl.innerHTML = `
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
          Tải & Chạy Game
        `;
      }
    });

    // 9. 1-Click Sync Zing Gunny Session from Chrome
    if (this.btnSyncZing) {
      this.btnSyncZing.addEventListener('click', async () => {
        this.btnSyncZing.disabled = true;
        this.btnSyncZing.textContent = '⏳ Đang đồng bộ từ Chrome...';
        this.logBridge('[Sync] Đang truy vấn phiên đăng nhập Gunny từ tab Chrome...');

        try {
          const res = await fetch('http://localhost:8081/sync-zing-session?sid=737');
          const data = await res.json();

          if (data.ok && data.swfUrl) {
            this.showToast(`🎉 Đồng bộ thành công Máy chủ ${data.serverId}! Đang nạp game...`);
            this.logBridge(`[Sync] Đã trích xuất SWF: ${data.swfUrl}`, 'success');
            this.logBridge(`[Sync] Đã xác thực User kufa91 (Server ${data.serverId})`, 'success');

            if (data.flashvars) {
              this.inputFlashvars.value = JSON.stringify(data.flashvars, null, 2);
            }

            const proxiedUrl = data.proxiedSwfUrl || this.bridge.getProxiedUrl(data.swfUrl);
            await this.runGame(proxiedUrl, { flashvars: data.flashvars || {} });
          } else {
            this.showToast(`⚠️ ${data.error || 'Không thể đồng bộ. Hãy chắc chắn tab Gunny đang mở.'}`, 5000);
            this.logBridge(`[Sync Error] ${data.error}`, 'error');
          }
        } catch (e) {
          this.showToast(`Lỗi đồng bộ: ${e.message}`, 5000);
          this.logBridge(`[Sync Error] ${e.message}`, 'error');
        } finally {
          this.btnSyncZing.disabled = false;
          this.btnSyncZing.textContent = '⚡ Đồng bộ & Vào Game Ngay (Gà Cầu Duyên)';
        }
      });
    }

    // 10. Custom Gunny Launch Button
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

    // 11. Prevent default browser scrolling on Game Keys (Space, Arrows) during gameplay
    window.addEventListener('keydown', (e) => {
      const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
      if (activeTag === 'input' || activeTag === 'textarea' || activeTag === 'select') return;

      if (['Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.code) && this.player.isLoaded) {
        e.preventDefault();
      }
    }, { passive: false });
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
