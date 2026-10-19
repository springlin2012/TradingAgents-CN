import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { searchStockCandidates, type StockNameCandidate } from '../api/stockData'

interface StockNameForm {
  stock_code: string
  stock_name: string
  market: string
}

export function useStockNameAutocomplete(
  form: Ref<StockNameForm>,
  visible: Ref<boolean>,
  clearSuggestions: () => void
) {
  const loading = ref(false)
  const hint = ref('')
  let timer: ReturnType<typeof setTimeout> | undefined
  let requestVersion = 0
  let inputVersion = 0
  let lookupVersion = 0
  let session = 0
  let selected: StockNameCandidate | null = null
  let automaticName = ''

  const clearSearch = () => {
    requestVersion++
    clearTimeout(timer)
    timer = undefined
    loading.value = false
    hint.value = ''
    clearSuggestions()
  }

  const invalidateInput = () => {
    inputVersion++
    lookupVersion++
    clearSearch()
  }

  const reset = () => {
    session++
    selected = null
    automaticName = ''
    invalidateInput()
  }

  const onNameInput = (value: string) => {
    if (selected && value !== selected.name) {
      form.value.stock_code = ''
      selected = null
    }
    automaticName = ''
    invalidateInput()
  }

  const onCodeInput = () => {
    if ((automaticName && form.value.stock_name === automaticName) ||
      (selected && form.value.stock_name === selected.name)) {
      form.value.stock_name = ''
    }
    selected = null
    automaticName = ''
    invalidateInput()
  }

  const fetchSuggestions = (
    query: string,
    callback: (stocks: StockNameCandidate[]) => void
  ) => {
    const keyword = query.trim()
    // 组件的延迟回调也需核对当前表单，关闭后不再发起请求。
    if (!visible.value || form.value.market !== 'A股' || keyword !== form.value.stock_name.trim()) {
      return
    }
    clearSearch()
    if (!keyword || keyword.length > 50 || selected?.name === query) {
      if (keyword.length > 50) hint.value = '股票名称搜索最多支持50个字符'
      callback([])
      return
    }
    const version = requestVersion
    const currentSession = session
    const isCurrent = () => version === requestVersion && session === currentSession &&
      visible.value && form.value.market === 'A股' && form.value.stock_name.trim() === keyword

    loading.value = true
    hint.value = '搜索中...'
    timer = setTimeout(async () => {
      timer = undefined
      try {
        const stocks = await searchStockCandidates(keyword, 10)
        if (!isCurrent()) return
        callback(stocks)
        hint.value = stocks.length ? '' : '未找到匹配股票，可输入完整代码和名称'
      } catch {
        if (!isCurrent()) return
        callback([])
        hint.value = '搜索暂时不可用，可手动填写'
      } finally {
        if (isCurrent()) loading.value = false
      }
    }, 300)
  }

  const selectStock = (stock: StockNameCandidate) => {
    if (!visible.value || form.value.market !== 'A股' || !/^\d{6}$/.test(stock.symbol)) return
    invalidateInput()
    form.value.stock_name = stock.name
    form.value.stock_code = stock.symbol
    selected = stock
    automaticName = stock.name
  }

  const beginCodeLookup = () => {
    const symbol = form.value.stock_code.trim()
    if (!visible.value || form.value.market !== 'A股' || !/^\d{6}$/.test(symbol) ||
      selected?.symbol === symbol) return null
    const version = ++lookupVersion
    const edits = inputVersion
    const currentSession = session
    return {
      symbol,
      isCurrent: () => lookupVersion === version && inputVersion === edits &&
        session === currentSession && visible.value && form.value.market === 'A股' &&
        form.value.stock_code.trim() === symbol && !selected
    }
  }

  const setCodeName = (name: string) => {
    clearSearch()
    form.value.stock_name = name
    automaticName = name
  }

  watch([visible, () => form.value.market], reset, { flush: 'sync' })
  onScopeDispose(reset)

  return {
    loading, hint, fetchSuggestions, onNameInput, onCodeInput, selectStock,
    beginCodeLookup, setCodeName, invalidateInput, reset
  }
}
