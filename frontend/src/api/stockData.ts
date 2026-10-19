import { ApiClient } from './request'

export interface StockNameCandidate {
  symbol: string
  name: string
  source: string
}

export async function searchStockCandidates(
  keyword: string,
  limit = 10
): Promise<StockNameCandidate[]> {
  const response = await ApiClient.get<StockNameCandidate[]>(
    '/api/stock-data/search',
    { keyword, limit, mode: 'autocomplete' },
    { skipErrorHandler: true, retryCount: 0 }
  )
  if (!response.success) {
    throw new Error(response.message || '搜索失败')
  }
  return response.data
}
