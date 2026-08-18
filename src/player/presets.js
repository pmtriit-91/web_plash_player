/**
 * Presets Library for Web Flash Player
 * Includes Gunny / DDTank server configs, retro game benchmarks, and sample SWFs
 */

export const GAME_PRESETS = [
  {
    id: 'gunny-123gn',
    name: '123gn.net (Gà Thiện Xạ - S1001)',
    category: 'Private Server ⚡',
    description: 'Máy chủ Gunny Private hồi ức với bộ định tuyến Smart Socket Gateway 15.235.193.106:25565 và One-Time Key trích xuất nguyên bản.',
    swfUrl: 'http://localhost:8081/host/123gn.net/flash3/Loading.swf',
    isGunny: true,
    isPrivate: true,
    serverUrl: 'https://123gn.net/play/1001',
    flashvars: {
      config: 'http://localhost:8081/host/123gn.net/flash3/config3.xml'
    },
    width: 1000,
    height: 600,
    aspectRatio: '5:3'
  },
  {
    id: 'gunny-zing-737',
    name: 'Zing Gunny (Gà Cầu Duyên - S737)',
    category: 'Zing Official ⚡',
    description: 'Máy chủ chính thức Zing Gunny Server 737. Tự động đồng bộ phiên chơi qua Chrome hoặc trích xuất cookie Zing ID.',
    swfUrl: 'http://localhost:8081/host/res737.gn.zing.vn/flash/Loading.swf',
    isGunny: true,
    isZing: true,
    serverUrl: 'https://id-levelup.gn.zing.vn',
    flashvars: {
      config: 'http://localhost:8081/host/s737.gn.zing.vn/config.xml'
    },
    width: 1000,
    height: 600,
    aspectRatio: '5:3'
  },
  {
    id: 'alien-hominid',
    name: 'Alien Hominid (Kinh điển)',
    category: 'Action Arcade Game',
    description: 'Game bắn súng Flash kinh điển nổi tiếng thế giới. Thử nghiệm đồ họa 60 FPS, âm thanh và bàn phím (A, S, Phím mũi tên).',
    swfUrl: '/samples/alien_hominid.swf',
    flashvars: {},
    width: 800,
    height: 600,
    aspectRatio: '4:3'
  },
  {
    id: 'flyguy-game',
    name: 'FlyGuy (Phiêu lưu)',
    category: 'Adventure / Interactive',
    description: 'Game phiêu lưu tương tác âm nhạc và hiệu ứng vector Flash mượt mà.',
    swfUrl: '/samples/flyguy.swf',
    flashvars: {},
    width: 800,
    height: 600,
    aspectRatio: '4:3'
  },
  {
    id: 'logo-anim',
    name: 'Flash Vector & Animation Demo',
    category: 'Vector Graphics',
    description: 'Trình diễn hiệu ứng đồ họa Vector và WebGL shader của WebAssembly Flash Engine.',
    swfUrl: '/samples/logo-anim.swf',
    flashvars: {},
    width: 800,
    height: 600,
    aspectRatio: '4:3'
  }
];
