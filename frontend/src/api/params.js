import http from './http'

const schemaPromises = new Map()
let programsPromise = null

export function getPrograms() {
  if (!programsPromise) {
    programsPromise = http.get('/programs').catch((err) => {
      programsPromise = null
      throw err
    })
  }
  return programsPromise
}

export function getParamSchema(programKey = 'dcr_3d') {
  if (!schemaPromises.has(programKey)) {
    const promise = http.get('/param-schema', { params: { program_key: programKey } })
      .catch((err) => {
        schemaPromises.delete(programKey)
        throw err
      })
    schemaPromises.set(programKey, promise)
  }
  return schemaPromises.get(programKey)
}
