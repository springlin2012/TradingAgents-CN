const assert = require('node:assert/strict')
const { test } = require('node:test')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('../../frontend/node_modules/typescript')
const vue = require('../../frontend/node_modules/vue')

const sourcePath = path.resolve(__dirname, '../../frontend/src/composables/useStockNameAutocomplete.ts')
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms))
const stock = (symbol, name) => ({ symbol, name, source: 'tushare' })

function setup() {
  assert.ok(fs.existsSync(sourcePath), '名称自动补全逻辑尚未实现')
  const requests = []
  const api = {
    searchStockCandidates: keyword => new Promise((resolve, reject) => {
      requests.push({ keyword, resolve, reject })
    })
  }
  const code = ts.transpileModule(fs.readFileSync(sourcePath, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }
  }).outputText
  const module = { exports: {} }
  vm.runInThisContext(`(function(require,module,exports){${code}\n})`, { filename: sourcePath })(
    name => name === 'vue' ? vue : api, module, module.exports
  )
  const form = vue.ref({ stock_code: '', stock_name: '', market: 'A股' })
  const visible = vue.ref(true)
  const scope = vue.effectScope()
  let resets = 0
  const search = scope.run(() => module.exports.useStockNameAutocomplete(form, visible, () => resets++))
  return { form, visible, requests, search, stop: () => scope.stop(), resets: () => resets }
}

test('输入防抖，候选名称和代码一起填入，修改名称清除旧代码', async () => {
  const ctx = setup()
  try {
    ctx.form.value.stock_name = '海'
    ctx.search.onNameInput('海')
    let results
    ctx.search.fetchSuggestions('海', value => { results = value })
    await delay(100)
    assert.equal(ctx.requests.length, 0)
    await delay(230)
    assert.equal(ctx.requests.length, 1)
    ctx.requests[0].resolve([stock('600690', '海尔智家')])
    await delay(0)
    assert.equal(results[0].name, '海尔智家')
    ctx.search.selectStock(results[0])
    assert.equal(ctx.form.value.stock_code, '600690')
    assert.equal(ctx.form.value.stock_name, '海尔智家')
    assert.equal(ctx.search.beginCodeLookup(), null)
    ctx.search.onNameInput('海天')
    assert.equal(ctx.form.value.stock_code, '')
  } finally { ctx.stop() }
})

test('防抖等待期间旧响应也不能覆盖新输入，新请求先完成时保持新结果', async () => {
  const ctx = setup()
  try {
    let oldCallbacks = 0
    let newResults
    ctx.form.value.stock_name = '海'
    ctx.search.onNameInput('海')
    ctx.search.fetchSuggestions('海', () => oldCallbacks++)
    await delay(330)
    ctx.form.value.stock_name = '平安'
    ctx.search.onNameInput('平安')
    ctx.search.fetchSuggestions('平安', value => { newResults = value })
    ctx.requests[0].resolve([stock('600690', '海尔智家')])
    await delay(0)
    assert.equal(oldCallbacks, 0)
    await delay(330)
    ctx.requests[1].resolve([stock('000001', '平安银行')])
    await delay(0)
    assert.equal(newResults[0].symbol, '000001')
    assert.equal(ctx.search.loading.value, false)
  } finally { ctx.stop() }
})

test('旧请求失败和finally不影响最新请求的加载与错误状态', async () => {
  const ctx = setup()
  try {
    ctx.form.value.stock_name = '海'
    ctx.search.onNameInput('海')
    ctx.search.fetchSuggestions('海', () => assert.fail('不应更新过期候选'))
    await delay(330)
    ctx.form.value.stock_name = '平安'
    ctx.search.onNameInput('平安')
    ctx.search.fetchSuggestions('平安', () => {})
    await delay(330)
    ctx.requests[0].reject(new Error('old request'))
    await delay(0)
    assert.equal(ctx.search.loading.value, true)
    assert.equal(ctx.search.hint.value, '搜索中...')
    ctx.requests[1].reject(new Error('network'))
    await delay(0)
    assert.match(ctx.search.hint.value, /搜索暂时不可用/)
    assert.equal(ctx.search.loading.value, false)
  } finally { ctx.stop() }
})

test('清空、切换市场、关闭重开都使旧请求失效，港美股不搜索', async () => {
  for (const action of ['clear', 'market', 'reopen']) {
    const ctx = setup()
    try {
      ctx.form.value.stock_name = '海'
      ctx.search.onNameInput('海')
      let callbacks = 0
      ctx.search.fetchSuggestions('海', () => callbacks++)
      await delay(330)
      if (action === 'clear') {
        ctx.form.value.stock_name = ''
        ctx.search.onNameInput('')
      } else if (action === 'market') {
        ctx.form.value.market = '港股'
      } else {
        ctx.visible.value = false
        ctx.visible.value = true
      }
      ctx.requests[0].resolve([stock('600690', '海尔智家')])
      await delay(0)
      assert.equal(callbacks, 0)
      assert.equal(ctx.search.hint.value, '')
      ctx.form.value.market = '美股'
      ctx.search.fetchSuggestions('Apple', () => {})
      await delay(330)
      assert.equal(ctx.requests.length, 1)
    } finally { ctx.stop() }
  }
})

test('手填代码不因名称编辑清空；旧代码查名不能覆盖名称编辑和重新打开', () => {
  const ctx = setup()
  try {
    ctx.form.value.stock_code = '000001'
    const lookup = ctx.search.beginCodeLookup()
    assert.equal(lookup.isCurrent(), true)
    ctx.search.onNameInput('手工名称')
    assert.equal(lookup.isCurrent(), false)
    assert.equal(ctx.form.value.stock_code, '000001')
    const nextLookup = ctx.search.beginCodeLookup()
    ctx.visible.value = false
    ctx.visible.value = true
    assert.equal(nextLookup.isCurrent(), false)
    ctx.search.setCodeName('平安银行')
    ctx.search.onCodeInput()
    assert.equal(ctx.form.value.stock_name, '')
  } finally { ctx.stop() }
})

test('空白和超长关键词不查询；无结果显示手填提示；销毁清理待发请求', async () => {
  const ctx = setup()
  try {
    for (const keyword of ['   ', '海'.repeat(51)]) {
      ctx.form.value.stock_name = keyword
      ctx.search.onNameInput(keyword)
      ctx.search.fetchSuggestions(keyword, () => {})
    }
    await delay(330)
    assert.equal(ctx.requests.length, 0)
    ctx.form.value.stock_name = '不存在'
    ctx.search.onNameInput('不存在')
    ctx.search.fetchSuggestions('不存在', () => {})
    await delay(330)
    ctx.requests[0].resolve([])
    await delay(0)
    assert.match(ctx.search.hint.value, /未找到匹配股票/)
    ctx.form.value.stock_name = '海'
    ctx.search.onNameInput('海')
    ctx.search.fetchSuggestions('海', () => {})
    ctx.stop()
    await delay(330)
    assert.equal(ctx.requests.length, 1)
  } finally { ctx.stop() }
})

test('名称仍等于已选股票时修改代码，也清除选中股票的名称', () => {
  const ctx = setup()
  try {
    ctx.search.selectStock(stock('600690', '海尔智家'))
    ctx.search.onNameInput('海尔智家')
    ctx.search.onCodeInput()
    assert.equal(ctx.form.value.stock_name, '')
  } finally { ctx.stop() }
})
