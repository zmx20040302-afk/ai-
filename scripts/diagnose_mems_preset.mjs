// 用 DSH 自己的发现/健康检查逻辑诊断「MEMS 模式」为何不可选。
// 用法：node scripts\diagnose_mems_preset.mjs
// 说明：旧版把包路径写死（C:/Users/18161/...），换机即失效——这里改为动态解析。
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

const base = join(findPresetPkg(), 'lib')
console.log('DSH agent-presets lib：', base)
// harnessBase = 含 node_modules 的 DSH 安装根（包名解析基准，等价于 DSH 的 ctx.baseUrl）；
// discoverPresets/scanRoot 的第二参必填，不传会因 undefined 抛错。
const harnessBase = pathToFileURL(join(base, '..', '..', '..', '..') + sep)
console.log('harnessBase：', harnessBase.href)
const discovery = await import(pathToFileURL(join(base, 'types', 'discovery.js')).href)
const index = await import(pathToFileURL(join(base, 'index.js')).href)

console.log('discovery 导出：', Object.keys(discovery).join(', '))
console.log('index 导出：', Object.keys(index).join(', '))

const root = join(process.env.DSH_HOME ?? join(homedir(), '.dsh'), '.agent-presets')

// 1) 走完整发现流程（DSH 启动时就是这个入口）
const roots = [{ path: root, trust: 'user' }]
const presets = await index.discoverPresets(roots, harnessBase)
for (const preset of presets) {
  console.log('\n=== preset 行 ===')
  console.log(JSON.stringify({
    id: preset.id,
    name: preset.name,
    broken: preset.broken,
    trust: preset.trust,
    path: preset.path,
  }, null, 2))
}

// 2) 直接对 composition 做健康检查（找出“不可加载”的具体原因）
const mems = presets.find((p) => p.id === 'mems')
if (!mems) {
  console.log('❌ 未发现 mems，检查根目录：', root)
  process.exit(1)
}

if (typeof discovery.rowsProblem === 'function' || typeof discovery.rowProblem === 'function') {
  const fn = discovery.rowsProblem ?? discovery.rowProblem
  const { readFile } = await import('node:fs/promises')
  const { parse } = await import('yaml').catch(() => ({ parse: null }))
  const text = await readFile(join(root, 'mems', 'agent.cordis.yml'), 'utf8')
  console.log('\n=== 原始文本健康检查 ===')
  console.log('rowsProblem(原始 YAML 文本)：', fn(text))
  if (parse) {
    console.log('rowsProblem(解析后数组)：', fn(parse(text)))
  }
} else {
  console.log('\n未导出健康检查函数，改看 preset 行的 broken 字段（见上）。')
}
