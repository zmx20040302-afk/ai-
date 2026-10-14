// 用 DSH 自己的 preset 发现逻辑验证「MEMS 模式」是否被识别（不启动 DSH 服务）。
// 用法：node scripts\verify_mems_preset.mjs
// 说明：DSH 的包可能来自 profile 的 node_modules，也可能来自 npx 缓存，
//       旧版脚本把绝对路径写死（C:/Users/18161/...），换机即失效——这里改为动态解析。
import { pathToFileURL } from 'node:url'
import { existsSync, readdirSync } from 'node:fs'
import { homedir } from 'node:os'
import { join, sep } from 'node:path'

/** 定位本机 @deepseek-ai/dsh-agent-presets 包目录。 */
function findPresetPkg() {
  const dsh = process.env.DSH_HOME ?? join(homedir(), '.dsh')
  const roots = []
  if (process.env.DSH_AGENT_PRESETS_PKG) roots.push(process.env.DSH_AGENT_PRESETS_PKG)
  roots.push(join(dsh, 'profiles', 'web', 'node_modules', '@deepseek-ai', 'dsh-agent-presets'))
  roots.push(join(dsh, 'profiles', 'node_modules', '@deepseek-ai', 'dsh-agent-presets'))
  const npx = process.env.LOCALAPPDATA ? join(process.env.LOCALAPPDATA, 'npm-cache', '_npx') : null
  if (npx && existsSync(npx)) {
    for (const entry of readdirSync(npx)) {
      roots.push(join(npx, entry, 'node_modules', '@deepseek-ai', 'dsh-agent-presets'))
    }
  }
  if (process.env.APPDATA) {
    roots.push(join(process.env.APPDATA, 'npm', 'node_modules', '@deepseek-ai', 'dsh-agent-presets'))
  }
  const hit = roots.find((p) => existsSync(join(p, 'lib', 'index.js')))
  if (!hit) {
    console.error('找不到 @deepseek-ai/dsh-agent-presets；请设置 DSH_AGENT_PRESETS_PKG 指向该包目录。')
    process.exit(2)
  }
  return hit
}

const pkgDir = findPresetPkg()
console.log('DSH agent-presets 包：', pkgDir)
const mod = await import(pathToFileURL(join(pkgDir, 'lib', 'index.js')).href)

// harnessBase = 含 node_modules 的 DSH 安装根（包名解析基准，等价于 DSH 的 ctx.baseUrl）。
// 不传它 → discoverPresets/scanRoot 内部解析包名时拿到 undefined 并抛错（旧脚本就是这样失败的）。
const harnessBase = pathToFileURL(join(pkgDir, '..', '..', '..') + sep)
console.log('harnessBase：', harnessBase.href)

console.log('导出成员：', Object.keys(mod).filter((k) => /preset|discover|scan|root/i.test(k)).join(', '))

const root = join(process.env.DSH_HOME ?? join(homedir(), '.dsh'), '.agent-presets')
console.log('用户 preset 根目录：', root)

if (typeof mod.discoverPresets !== 'function') {
  console.log('未导出 discoverPresets，改用 scanRoot')
}

// 注意 roots 的字段名是 `trust`（不是 source）
const roots = [{ path: root, trust: 'user' }]
let presets = []
try {
  presets = await mod.discoverPresets(roots, harnessBase)
} catch (error) {
  console.log('discoverPresets 失败：', String(error))
  try {
    presets = await mod.scanRoot({ path: root, trust: 'user' }, harnessBase)
  } catch (error2) {
    console.log('scanRoot 也失败：', String(error2))
  }
}

console.log(`发现 ${presets.length} 个用户 preset：`)
for (const preset of presets) {
  const broken = preset.broken ? ` broken=${preset.broken}` : '（健康，无 broken 字段）'
  console.log(`  - id=${preset.id} name=${preset.metadata?.name ?? preset.name}${broken}`)
}
const mems = presets.find((p) => p.id === 'mems')
console.log(mems ? '✅ MEMS 模式已被 DSH 发现' : '❌ 未发现 MEMS 模式')
