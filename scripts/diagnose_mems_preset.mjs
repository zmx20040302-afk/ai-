// 用 DSH 自己的发现/健康检查逻辑诊断「MEMS 模式」为何不可选。
// 用法：D:\node.exe scripts\diagnose_mems_preset.mjs
import { pathToFileURL } from 'node:url'
import { homedir } from 'node:os'
import { join } from 'node:path'

const base = 'C:/Users/18161/.dsh/profiles/node_modules/@deepseek-ai/dsh-agent-presets/lib'
const discovery = await import(pathToFileURL(`${base}/types/discovery.js`).href)
const index = await import(pathToFileURL(`${base}/index.js`).href)

console.log('discovery 导出：', Object.keys(discovery).join(', '))
console.log('index 导出：', Object.keys(index).join(', '))

const root = join(homedir(), '.dsh', '.agent-presets')

// 1) 走完整发现流程（DSH 启动时就是这个入口）
const roots = [{ path: root, trust: 'user' }]
const presets = await index.discoverPresets(roots)
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

// 2) 直接对 composition 做健康检查（找出"不可加载"的具体原因）
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
