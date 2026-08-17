/**
 * Presets Library for Web Flash Player
 * Includes Gunny / DDTank server configs, retro game benchmarks, and sample SWFs
 */

export const GAME_PRESETS = [
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
    id: 'gunny-local',
    name: 'Gunny DDTank (Cấu hình Server)',
    category: 'MMORPG / Gunny DDTank',
    description: 'Cấu hình kết nối Game Server Gunny qua WebSocket-to-TCP Bridge (AVM2 / ActionScript 3.0).',
    swfUrl: 'http://localhost:8081/proxy?url=http://127.0.0.1/resource/Loading.swf',
    isGunny: true,
    serverConfig: {
      host: '127.0.0.1',
      port: 9200,
      resourcePath: 'http://127.0.0.1/resource/',
      user: 'admin',
      key: 'gunny_session_key'
    },
    flashvars: {
      user: 'player_test',
      key: 'd41d8cd98f00b204e9800998ecf8427e',
      v: '1000',
      rand: '123456',
      config: 'http://127.0.0.1/config.xml'
    },
    width: 1000,
    height: 600,
    aspectRatio: '5:3'
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
