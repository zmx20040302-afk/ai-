// 从 PyPI 取 uv 的 Windows x64 wheel（GitHub 直连超时，PyPI 可达）
import fs from 'node:fs';

const meta = await (await fetch('https://pypi.org/pypi/uv/json')).json();
const wheels = meta.urls.filter((u) => u.filename.endsWith('win_amd64.whl'));
if (wheels.length === 0) {
  console.error('no win_amd64 wheel found');
  process.exit(1);
}
const pick = wheels[0];
console.log('picked', pick.filename, pick.size, 'bytes');

const r = await fetch(pick.url);
if (!r.ok) {
  console.error('HTTP', r.status);
  process.exit(1);
}
const buf = Buffer.from(await r.arrayBuffer());
fs.mkdirSync('work/tools', { recursive: true });
fs.writeFileSync('work/tools/uv.whl', buf);
console.log('saved work/tools/uv.whl', buf.length, 'bytes');
