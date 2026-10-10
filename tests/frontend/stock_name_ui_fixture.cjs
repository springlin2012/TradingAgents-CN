// 本地浏览器验收用模拟接口，数据仅保存在内存；不连接业务数据库。
const http = require('node:http')
const stocks = [
  { symbol: '600690', name: '海尔智家', source: 'tushare' },
  { symbol: '603288', name: '海天味业', source: 'akshare' },
  { symbol: '000001', name: '平安银行', source: 'tushare' }
]
const favorites = []
const requests = []
const user = { id: 'ui-test', username: 'ui-test', email: 'test@example.invalid', is_admin: true, preferences: {} }
const token = ['eyJhbGciOiJub25lIn0', Buffer.from(JSON.stringify({ sub: 'ui-test', exp: 4102444800 })).toString('base64url'), 'ui-fixture'].join('.')
const server = http.createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', 'http://127.0.0.1:3000')
  res.setHeader('Access-Control-Allow-Headers', '*')
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
  if (req.method === 'OPTIONS') { res.writeHead(204).end(); return }
  const url = new URL(req.url, 'http://127.0.0.1:18000')
  const reply = (data, success = true, status = 200, message = '获取成功') => {
    res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' })
    res.end(JSON.stringify({ success, data, message }))
  }
  requests.push({ path: url.pathname, keyword: url.searchParams.get('keyword'), method: req.method })
  if (url.pathname === '/__requests') { reply(requests); return }
  if (url.pathname === '/api/auth/login' || url.pathname === '/api/auth/refresh') {
    reply({ access_token: token, refresh_token: token, user }); return
  }
  if (url.pathname === '/api/auth/me') { reply(user); return }
  if (url.pathname === '/api/stock-data/search') {
    const keyword = url.searchParams.get('keyword') || ''
    await new Promise(resolve => setTimeout(resolve, keyword === '海' ? 400 : 20))
    if (keyword === '失败') { reply(null, false, 500, '测试搜索失败'); return }
    const data = stocks.filter(stock => stock.name.includes(keyword))
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' })
    res.end(JSON.stringify({ success: true, data, total: data.length, source: 'mixed', keyword, message: '搜索完成' }))
    return
  }
  if (url.pathname.startsWith('/api/stock-data/basic-info/')) {
    const code = url.pathname.split('/').at(-1)
    await new Promise(resolve => setTimeout(resolve, 400))
    const stock = stocks.find(stock => stock.symbol === code)
    reply(stock || null, !!stock); return
  }
  if (url.pathname === '/api/favorites/' && req.method === 'POST') {
    let body = ''
    for await (const chunk of req) body += chunk
    const data = JSON.parse(body)
    if (favorites.some(item => item.stock_code === data.stock_code)) {
      reply(null, false, 400, '该股票已在自选股中'); return
    }
    favorites.push({ ...data, added_at: new Date().toISOString() })
    reply({ stock_code: data.stock_code }, true, 200, '添加成功'); return
  }
  if (url.pathname === '/api/favorites/') { reply(favorites); return }
  if (url.pathname === '/api/tags/') { reply([]); return }
  if (url.pathname.includes('unread-count')) { reply({ count: 0 }); return }
  reply({ items: [], count: 0 })
})
server.listen(18000, '127.0.0.1', () => console.log('验收模拟接口：http://127.0.0.1:18000'))
// 页面健康探测走 Vite 的默认代理，复用同一内存接口处理器。
http.createServer(server.listeners('request')[0]).listen(8000, '127.0.0.1')
