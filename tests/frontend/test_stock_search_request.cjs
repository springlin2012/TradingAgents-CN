const assert = require('node:assert/strict')
const { test } = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../frontend/node_modules/typescript')

function setup() {
  const messages = []
  const redirects = []
  let handler
  let cleared = false
  const instance = {
    interceptors: { request: { use() {} }, response: { use(_success, failure) { handler = failure } } }
  }
  const imports = {
    axios: { default: { create: () => instance } },
    'element-plus': { ElMessage: { error: value => messages.push(value) } },
    '@/stores/app': { useAppStore: () => ({}) },
    '@/stores/auth': { useAuthStore: () => ({ clearAuthInfo() { cleared = true } }) },
    '@/router': { default: { push: value => redirects.push(value) } }
  }
  const file = path.resolve(__dirname, '../../frontend/src/api/request.ts')
  const source = fs.readFileSync(file, 'utf8').replaceAll('import.meta.env', '({})')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }
  }).outputText
  const context = vm.createContext({
    require: name => imports[name], module: { exports: {} }, exports: {},
    console: { log() {}, error() {}, warn() {} }, setTimeout() {},
    Map, Date, Promise, Error
  })
  vm.runInContext(compiled, context, { filename: file })
  return { handler: error => handler(error), messages, redirects, cleared: () => cleared }
}

test('静默搜索请求的HTTP错误不弹全局提示，仍拒绝请求', async () => {
  for (const status of [400, 403, 404, 422, 429, 500, 502, 503, 504]) {
    const ctx = setup()
    const error = { message: '搜索失败', response: { status, data: {} }, config: { skipErrorHandler: true, retryCount: 0 } }
    await assert.rejects(ctx.handler(error))
    assert.equal(ctx.messages.length, 0, `HTTP ${status} 应由名称字段处理`)
  }
})

test('静默搜索的超时和网络失败不弹全局提示', async () => {
  for (const error of [
    { message: 'timeout', code: 'ECONNABORTED' },
    { message: 'Network Error' },
    { message: 'Failed to fetch' }
  ]) {
    const ctx = setup()
    await assert.rejects(ctx.handler({ ...error, config: { skipErrorHandler: true, retryCount: 0 } }))
    assert.equal(ctx.messages.length, 0)
  }
})

test('普通请求仍显示错误，静默请求的401仍按鉴权流程处理', async () => {
  const normal = setup()
  await assert.rejects(normal.handler({ message: '失败', response: { status: 500, data: {} }, config: {} }))
  assert.equal(normal.messages.length, 1)
  const auth = setup()
  await assert.rejects(auth.handler({ message: '过期', response: { status: 401, data: {} }, config: { skipErrorHandler: true } }))
  assert.equal(auth.cleared(), true)
  assert.deepEqual(auth.redirects, ['/login'])
  assert.equal(auth.messages.length, 1)
})
