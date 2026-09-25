// Thin client for the SWIRL HTTP API. No science here: everything is computed server-side.

export interface SpectrumSummary {
  id: string
  name: string
  source: string
  quantity: string
  n_bands: number
  wl_min: number
  wl_max: number
}

export interface HistoryStep {
  name: string
  params: Record<string, unknown>
  swirl_version: string
}

export interface SpectrumData {
  id: string
  name: string
  quantity: string
  wavelength: (number | null)[]
  values: (number | null)[]
  meta: Record<string, unknown>
  history: HistoryStep[]
}

export type SpectrumDetail = SpectrumSummary & SpectrumData

export interface JsonSchema {
  type?: string
  title?: string
  description?: string
  default?: unknown
  enum?: unknown[]
  const?: unknown
  anyOf?: JsonSchema[]
  items?: JsonSchema
  prefixItems?: JsonSchema[]
  properties?: Record<string, JsonSchema>
  required?: string[]
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
}

export interface OperationInfo {
  name: string
  summary: string
  schema: JsonSchema
}

export interface StepPayload {
  op: string
  params: Record<string, unknown>
}

export interface FieldError {
  loc: (string | number)[]
  msg: string
}

export interface StepProblem {
  step: number
  op: string
  errors: FieldError[]
}

export interface GroupError {
  ids: string[]
  message: string
}

export interface QcResult {
  id: string
  name: string
  metrics: Record<string, number | null>
  flags: string[]
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === 'string' ? detail : `request failed (${status})`)
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { 'Content-Type': 'application/json' }
  }
  const res = await fetch(url, init)
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      detail = (await res.json()).detail
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail)
  }
  const type = res.headers.get('content-type') ?? ''
  return (type.includes('application/json') ? res.json() : res.text()) as Promise<T>
}

interface Added {
  added: SpectrumSummary[]
  errors: { file: string; message: string }[]
}

export const api = {
  health: () => request<{ status: string; version: string }>('GET', '/api/health'),
  spectra: () => request<SpectrumSummary[]>('GET', '/api/spectra'),
  spectrum: (id: string) => request<SpectrumDetail>('GET', `/api/spectra/${id}`),
  upload(files: File[]) {
    const form = new FormData()
    for (const f of files) form.append('files', f, f.name)
    return request<Added>('POST', '/api/spectra/upload', form)
  },
  examples: () => request<Added>('POST', '/api/spectra/examples'),
  remove: (id: string) => request<unknown>('DELETE', `/api/spectra/${id}`),
  clear: () => request<unknown>('DELETE', '/api/spectra'),
  operations: () => request<OperationInfo[]>('GET', '/api/operations'),
  process: (ids: string[], steps: StepPayload[]) =>
    request<{ results: SpectrumData[]; errors: GroupError[] }>('POST', '/api/process', {
      ids,
      steps,
    }),
  exportCsv: (ids: string[], steps: StepPayload[]) =>
    request<string>('POST', '/api/export', { ids, steps }),
  parseRecipe: (text: string, filename: string) =>
    request<{ name: string; description: string; steps: StepPayload[] }>(
      'POST',
      '/api/recipe/parse',
      { text, filename },
    ),
  qcSchema: () => request<JsonSchema>('GET', '/api/qc/schema'),
  qc: (ids: string[], params: Record<string, unknown>) =>
    request<{ results: QcResult[]; errors: GroupError[] }>('POST', '/api/qc', { ids, params }),
}
