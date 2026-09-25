// Thin client for the SWIRL HTTP API. No science here: everything is computed server-side.

export interface SpectrumSummary {
  id: string
  name: string
  source: string
  quantity: string
  n_bands: number
  wl_min: number
  wl_max: number
  file: string | null
  hole_id: string | null
  depth_from: number | null
  depth_to: number | null
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
  wavelength: Float32Array
  values: Float32Array
  meta: Record<string, unknown>
  history: HistoryStep[]
}

/** Large arrays arrive as little-endian float32 in base64 (NaN kept). */
interface Packed {
  f32: string
  shape: number[]
}

export function unpack(p: Packed): Float32Array {
  const bin = atob(p.f32)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new Float32Array(bytes.buffer)
}

function unpackRows(p: Packed): Float32Array[] {
  const flat = unpack(p)
  const [rows, cols] = p.shape.length === 2 ? p.shape : [1, flat.length]
  return Array.from({ length: rows }, (_, r) => flat.subarray(r * cols, (r + 1) * cols))
}

type Wire<T> = Omit<T, 'wavelength' | 'values'> & { wavelength: Packed; values: Packed }

function decode<T extends { wavelength: Float32Array; values: Float32Array }>(raw: Wire<T>): T {
  return { ...raw, wavelength: unpack(raw.wavelength), values: unpack(raw.values) } as T
}

/** Responses listing many spectra send each wavelength axis once, in ``grids``. */
type GridWire<T> = Omit<T, 'wavelength' | 'values'> & { grid: string; values: Packed }

function decodeWithGrids<T extends { wavelength: Float32Array; values: Float32Array }>(
  items: GridWire<T>[],
  grids: Record<string, Packed>,
): T[] {
  const axes = Object.fromEntries(Object.entries(grids).map(([k, p]) => [k, unpack(p)]))
  return items.map((raw) => ({ ...raw, wavelength: axes[raw.grid], values: unpack(raw.values) }) as unknown as T)
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

export interface BandMeasure {
  position: number | null
  depth: number | null
  width: number | null
  asymmetry: number | null
  curvature: number | null
  status: 'minimum' | 'shoulder' | 'absent' | 'no_data'
  continuum: string
}

export interface BandTruth {
  center: number
  depth: number
  fwhm: number
  assignment: string
}

export interface BandRow {
  id: string
  name: string
  bands: Record<string, BandMeasure>
  ratios: Record<string, number | null>
  truth: Record<string, BandTruth> | null
}

export interface BandDefinition {
  name: string
  center: number
  lo: number
  hi: number
}

export interface HoleInfo {
  hole_id: string
  n: number
  top: number
  bottom: number
}

export interface HoleLogData {
  hole_id: string
  ids: string[]
  names: string[]
  depth_from: (number | null)[]
  depth_to: (number | null)[]
  quantity: string
  image: { wavelength: Float32Array; values: Float32Array[] }
  mean_reflectance: (number | null)[]
  bands: Record<string, { position: (number | null)[]; depth: (number | null)[]; width: (number | null)[]; asymmetry: (number | null)[]; status: string[] }>
  ratios: Record<string, (number | null)[]>
  qc: string[][] | null
  truth: { composition: Record<string, (number | null)[]>; aloh_center: (number | null)[] | null } | null
  notes: string[]
}

export interface OpenedProject {
  name: string
  created: string
  saved: string
  swirl_version: string
  settings: Record<string, unknown>
  spectra: SpectrumSummary[]
  visible_ids: string[]
  focused_id: string | null
  warnings: string[]
}

export interface AssignRow {
  id: string
  key: string
  hole_id: string | null
  depth_from: number | null
  depth_to: number | null
  current_hole: string | null
  status: 'ok' | 'unmatched' | 'duplicate'
}

export interface AssignSummary {
  matched: number
  unmatched: number
  holes: HoleInfo[]
  warnings: string[]
}

export interface NamingExample {
  name: string
  hole: [number, number]
  depth: [number, number]
}

export interface TableMappingIn {
  key: string | null
  hole: string | null
  depth_from: string | null
  depth_to: string | null
  match_on: 'name' | 'file'
  ignore_case: boolean
  ignore_extension: boolean
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

async function requestBlob(url: string, body: unknown): Promise<Blob> {
  const res = await fetch(url, {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      detail = (await res.json()).detail
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail)
  }
  return res.blob()
}

export const api = {
  health: () => request<{ status: string; version: string }>('GET', '/api/health'),
  spectra: () => request<SpectrumSummary[]>('GET', '/api/spectra'),
  spectrum: async (id: string) => decode<SpectrumDetail>(await request<Wire<SpectrumDetail>>('GET', `/api/spectra/${id}`)),
  async spectraData(ids: string[]) {
    const r = await request<{ spectra: GridWire<SpectrumDetail>[]; grids: Record<string, Packed> }>(
      'POST',
      '/api/spectra/data',
      { ids },
    )
    return decodeWithGrids<SpectrumDetail>(r.spectra, r.grids)
  },
  upload(files: File[]) {
    const form = new FormData()
    for (const f of files) form.append('files', f, f.name)
    return request<Added>('POST', '/api/spectra/upload', form)
  },
  examples: () => request<Added>('POST', '/api/spectra/examples'),
  exampleHole: () => request<Added>('POST', '/api/spectra/examples/hole'),
  exampleNamed: () => request<Added>('POST', '/api/spectra/examples/named'),
  namingPreview: (examples: NamingExample[], source: 'name' | 'file') =>
    request<{ rules: string[]; single_rule: boolean; rows: AssignRow[]; summary: AssignSummary }>(
      'POST',
      '/api/holes/naming/preview',
      { examples, source },
    ),
  namingApply: (examples: NamingExample[], source: 'name' | 'file') =>
    request<{ applied: number; spectra: SpectrumSummary[] }>('POST', '/api/holes/naming/apply', { examples, source }),
  tableUpload(file: File) {
    const form = new FormData()
    form.append('file', file, file.name)
    return request<{
      table_id: string
      filename: string
      columns: string[]
      n_rows: number
      head: string[][]
      mapping: Record<string, string | null>
    }>('POST', '/api/holes/table', form)
  },
  tablePreview: (table_id: string, mapping: TableMappingIn) =>
    request<{ rows: AssignRow[]; summary: AssignSummary }>('POST', '/api/holes/table/preview', { table_id, mapping }),
  tableApply: (table_id: string, mapping: TableMappingIn) =>
    request<{ applied: number; spectra: SpectrumSummary[] }>('POST', '/api/holes/table/apply', { table_id, mapping }),
  clearHoles: (ids: string[] | null) =>
    request<{ spectra: SpectrumSummary[] }>('POST', '/api/holes/clear', { ids }),
  holes: () => request<HoleInfo[]>('GET', '/api/holes'),
  log: async (body: {
    hole_id: string
    steps: StepPayload[]
    band_params: Record<string, unknown>
    qc_params: Record<string, unknown>
    image_max_bands?: number
  }) => {
    const raw = await request<Omit<HoleLogData, 'image'> & { image: { wavelength: Packed; values: Packed } }>(
      'POST',
      '/api/log',
      body,
    )
    return { ...raw, image: { wavelength: unpack(raw.image.wavelength), values: unpackRows(raw.image.values) } } as HoleLogData
  },
  remove: (id: string) => request<unknown>('DELETE', `/api/spectra/${id}`),
  clear: () => request<unknown>('DELETE', '/api/spectra'),
  operations: () => request<OperationInfo[]>('GET', '/api/operations'),
  async process(ids: string[], steps: StepPayload[], withInputs: string[] = []) {
    const r = await request<{
      results: GridWire<SpectrumData>[]
      errors: GroupError[]
      inputs: GridWire<SpectrumDetail>[]
      grids: Record<string, Packed>
    }>('POST', '/api/process', { ids, steps, with_inputs: withInputs })
    return {
      results: decodeWithGrids<SpectrumData>(r.results, r.grids),
      errors: r.errors,
      inputs: decodeWithGrids<SpectrumDetail>(r.inputs, r.grids),
    }
  },
  exportCsv: (ids: string[], steps: StepPayload[]) =>
    request<string>('POST', '/api/export', { ids, steps }),
  parseRecipe: (text: string, filename: string) =>
    request<{ name: string; description: string; steps: StepPayload[] }>(
      'POST',
      '/api/recipe/parse',
      { text, filename },
    ),
  bandsSchema: () => request<JsonSchema & { $defs?: unknown }>('GET', '/api/bands/schema'),
  bands: (ids: string[], steps: StepPayload[], params: Record<string, unknown>) =>
    request<{ rows: BandRow[]; errors: GroupError[] }>('POST', '/api/bands', { ids, steps, params }),
  bandsExport: (ids: string[], steps: StepPayload[], params: Record<string, unknown>) =>
    request<string>('POST', '/api/bands/export', { ids, steps, params }),
  saveProject: (body: {
    name: string
    created: string | null
    settings: Record<string, unknown>
    visible_ids: string[]
    focused_id: string | null
  }) => requestBlob('/api/project/save', body),
  openProject(file: File) {
    const form = new FormData()
    form.append('file', file, file.name)
    return request<OpenedProject>('POST', '/api/project/open', form)
  },
  qcSchema: () => request<JsonSchema>('GET', '/api/qc/schema'),
  qc: (ids: string[], params: Record<string, unknown>) =>
    request<{ results: QcResult[]; errors: GroupError[] }>('POST', '/api/qc', { ids, params }),
}
