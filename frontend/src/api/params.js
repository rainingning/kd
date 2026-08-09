import http from './http'

// 参数 Schema 基本不变，做模块级缓存避免重复请求
let schemaPromise = null

export function getParamSchema() {
  if (!schemaPromise) {
    schemaPromise = http.get('/param-schema').catch((err) => {
      schemaPromise = null
      throw err
    })
  }
  return schemaPromise
}
