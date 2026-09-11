// 用 DSH 自己的 preset 发现逻辑验证「MEMS 模式」是否被识别（不启动 DSH 服务）。
// 用法：D:\node.exe scripts\verify_mems_preset.mjs
import { pathToFileURL } from 'node:url'
import { homedir } from 'node:os'
import { join } from 'node:path'

const pkgPath = 'C:/Users/18161/.dsh/profiles/node_modules/@deepseek-ai/dsh-agent-presets/lib/index.js'
const mod = await import(pathToFileURL(pkgPath).href)

console.log('导出成员：', Object.keys(mod).filter((k) => /preset|discover|scan|root/i.test(k)).join(', '))

const root = join(homedir(), '.dsh', '.agent-presets')
console.log('用户 preset 根目录：', root)

if (typeof mod.discoverPresets !== 'function') {
  console.log('未导出 discoverPresets，改用 scanRoot')
}

const roots = [{ path: root, source: 'user' }]
let presets = []
try {
  presets = await mod.discoverPresets(roots)
} catch (error) {
  console.log('discoverPresets 失败：', String(error))
  try {
    presets = await mod.scanRoot(root)
  } catch (error2) {
    console.log('scanRoot 也失败：', String(error2))
  }
}

console.log(`发现 ${presets.length} 个用户 preset：`)
for (const preset of presets) {
  console.log(`  - id=${preset.id} name=${preset.metadata?.name ?? preset.name} order=${preset.metadata?.order ?? '?'}`)
}
const mems = presets.find((p) => p.id === 'mems')
console.log(mems ? '✅ MEMS 模式已被 DSH 发现' : '❌ 未发现 MEMS 模式')
