/**
 * Web Flash Player Pro — Electron Desktop Application Wrapper
 * Universal Agent OS 9.1
 */

const { app, BrowserWindow, shell, ipcMain } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');

let mainWindow = null;
let bridgeProcess = null;

const VITE_PORT = 5173;
const BRIDGE_HTTP_PORT = 8081;

// 1. Check if Bridge Server is already running, if not spawn it
function ensureBridgeServer() {
  const req = http.get(`http://localhost:${BRIDGE_HTTP_PORT}/health`, (res) => {
    if (res.statusCode === 200) {
      console.log('[Electron] Bridge server already running.');
    }
  });

  req.on('error', () => {
    console.log('[Electron] Spawning internal Bridge daemon...');
    const bridgePath = path.join(__dirname, '..', 'server', 'bridge.js');
    bridgeProcess = spawn(process.execPath, [bridgePath], {
      stdio: 'inherit',
      env: process.env
    });

    bridgeProcess.on('error', (err) => {
      console.error('[Electron] Failed to start Bridge process:', err);
    });
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1000,
    minHeight: 650,
    backgroundColor: '#080b12',
    title: 'Web Flash Player Pro',
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      plugins: true,
      webgl: true,
      backgroundThrottling: false,
      devTools: true
    }
  });

  // Load Vite Dev Server URL or Local Dist
  const appUrl = `http://localhost:${VITE_PORT}`;
  mainWindow.loadURL(appUrl).catch(() => {
    // If dev server not yet ready, load built dist
    const distPath = path.join(__dirname, '..', 'dist', 'index.html');
    mainWindow.loadFile(distPath);
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http:') || url.startsWith('https:')) {
      shell.openExternal(url);
    }
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  ensureBridgeServer();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('will-quit', () => {
  if (bridgeProcess) {
    bridgeProcess.kill();
  }
});
