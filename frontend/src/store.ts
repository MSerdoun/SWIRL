// Application state. Everything computed (processing, QC) comes back from the API; this
// module only keeps what the user chose and what the server returned.

import { computed, reactive, watch } from 'vue'

import {
  api,
  ApiError,
  type BandDefinition,
  type BandRow,
  type HoleInfo,
  type HoleLogData,
  type JsonSchema,
  type OperationInfo,
  type QcResult,
  type SpectrumData,
  type SpectrumDetail,
  type SpectrumSummary,
  type StepPayload,
  type StepProblem,
} from './api'
import { defaults } from './schema'

export interface UiStep {
  uid: number
  op: string
  params: Record<string, unknown>
  enabled: boolean
  open: boolean
  localErrors: Record<string, string>
  serverErrors: Record<string, string>
}

export type ViewMode = 'input' | 'processed' | 'both'

let nextUid = 1

export const state = reactive({
  ready: false,
  version: '',
  spectra: [] as SpectrumSummary[],
  visible: {} as Record<string, boolean>,
  slots: {} as Record<string, number>,
  focused: null as string | null,
  inputs: {} as Record<string, SpectrumDetail>,
  operations: [] as OperationInfo[],
  steps: [] as UiStep[],
  recipeName: '',
  processed: {} as Record<string, SpectrumData>,
  processErrors: [] as string[],
  processing: false,
  viewMode: 'both' as ViewMode,
  qcSchema: null as JsonSchema | null,
  qcParams: {} as Record<string, unknown>,
  qcLocalErrors: {} as Record<string, string>,
  qcServerErrors: {} as Record<string, string>,
  qcResults: [] as QcResult[],
  qcErrors: [] as string[],
  bandSchema: null as JsonSchema | null,
  bandParams: {} as Record<string, unknown>,
  bandLocalErrors: {} as Record<string, string>,
  bandServerErrors: {} as Record<string, string>,
  bandRows: [] as BandRow[],
  bandErrors: [] as string[],
  bandBusy: false,
  showBandMarkers: true,
  showBandWindows: true,
  mainView: 'spectra' as 'spectra' | 'drillhole',
  // Quick continuum removal applied after the recipe (a real, recorded step).
  continuum: { on: true, start: '', stop: '' },
  continuumError: '',
  holes: [] as HoleInfo[],
  selectedHole: null as string | null,
  log: null as HoleLogData | null,
  logBusy: false,
  logErrors: [] as string[],
  logTracks: [] as string[],
  busy: false,
  notice: { show: false, text: '', color: 'error' },
})

export const visibleIds = computed(() => state.spectra.filter((s) => state.visible[s.id]).map((s) => s.id))

export function notify(text: string, color = 'error') {
  state.notice = { show: true, text, color }
}

function message(err: unknown): string {
  if (err instanceof ApiError) return typeof err.detail === 'string' ? err.detail : err.message
  return err instanceof Error ? err.message : String(err)
}

// --- colour slots: stable per spectrum while visible, never re-assigned by rank ----------

function assignSlot(id: string) {
  if (state.slots[id] !== undefined) return
  const used = new Set(Object.values(state.slots))
  let slot = -1
  for (let i = 0; i < 8; i++)
    if (!used.has(i)) {
      slot = i
      break
    }
  state.slots[id] = slot
}

function releaseSlot(id: string) {
  delete state.slots[id]
}

export function setVisible(id: string, on: boolean) {
  state.visible[id] = on
  if (on) {
    assignSlot(id)
    void ensureInput(id)
  } else releaseSlot(id)
}

export function setAllVisible(on: boolean) {
  for (const s of state.spectra) setVisible(s.id, on)
}

async function ensureInput(id: string) {
  if (state.inputs[id]) return
  try {
    state.inputs[id] = await api.spectrum(id)
  } catch (err) {
    notify(message(err))
  }
}

// --- workspace ---------------------------------------------------------------------------

export async function init() {
  try {
    const [health, ops, spectra, qcSchema, bandSchema] = await Promise.all([
      api.health(),
      api.operations(),
      api.spectra(),
      api.qcSchema(),
      api.bandsSchema(),
    ])
    state.bandSchema = bandSchema
    state.bandParams = defaults(bandSchema)
    state.version = health.version
    state.operations = ops
    state.qcSchema = qcSchema
    state.qcParams = defaults(qcSchema)
    state.spectra = spectra
    for (const s of spectra.slice(0, 8)) setVisible(s.id, true)
    await refreshHoles()
    state.ready = true
  } catch (err) {
    notify(`Cannot reach the SWIRL server: ${message(err)}`)
  }
}

function addLoaded(added: SpectrumSummary[], errors: { file: string; message: string }[]) {
  state.spectra.push(...added)
  let shown = visibleIds.value.length
  for (const s of added) {
    if (shown < 8) {
      setVisible(s.id, true)
      shown++
    } else state.visible[s.id] = false
  }
  if (errors.length)
    notify(errors.map((e) => `${e.file}: ${e.message}`).join('\n'))
  else if (added.length) notify(`${added.length} spectrum(s) loaded`, 'success')
  void refreshHoles()
}

export async function uploadFiles(files: File[]) {
  if (!files.length) return
  state.busy = true
  try {
    const r = await api.upload(files)
    addLoaded(r.added, r.errors)
  } catch (err) {
    notify(message(err))
  } finally {
    state.busy = false
  }
}

export async function loadExamples() {
  state.busy = true
  try {
    const r = await api.examples()
    addLoaded(r.added, r.errors)
  } catch (err) {
    notify(message(err))
  } finally {
    state.busy = false
  }
}

export async function removeSpectrum(id: string) {
  try {
    await api.remove(id)
  } catch (err) {
    notify(message(err))
    return
  }
  state.spectra = state.spectra.filter((s) => s.id !== id)
  delete state.visible[id]
  delete state.inputs[id]
  delete state.processed[id]
  releaseSlot(id)
  if (state.focused === id) state.focused = null
  void refreshHoles()
}

export async function clearWorkspace() {
  try {
    await api.clear()
  } catch (err) {
    notify(message(err))
    return
  }
  state.spectra = []
  state.visible = {}
  state.slots = {}
  state.inputs = {}
  state.processed = {}
  state.focused = null
  void refreshHoles()
}

// --- recipe ------------------------------------------------------------------------------

export function addStep(op: string, params?: Record<string, unknown>) {
  const info = state.operations.find((o) => o.name === op)
  if (!info) return
  for (const s of state.steps) s.open = false
  state.steps.push({
    uid: nextUid++,
    op,
    params: params ?? defaults(info.schema),
    enabled: true,
    open: true,
    localErrors: {},
    serverErrors: {},
  })
}

export function moveStep(index: number, delta: number) {
  const j = index + delta
  if (j < 0 || j >= state.steps.length) return
  const [s] = state.steps.splice(index, 1)
  state.steps.splice(j, 0, s)
}

export function removeStep(index: number) {
  state.steps.splice(index, 1)
}

export const recipeRemovesContinuum = computed(() =>
  state.steps.some((s) => s.enabled && s.op === 'continuum_removal'),
)

function parseBound(text: string, what: string): number | null {
  const t = String(text ?? '').trim().replace(',', '.')
  if (t === '') return null
  const v = Number(t)
  if (Number.isNaN(v)) throw new Error(`continuum ${what}: "${text}" is not a number`)
  return v
}

/** The quick continuum-removal step, when switched on and not already in the recipe. */
export function continuumStep(): StepPayload | null {
  state.continuumError = ''
  if (!state.continuum.on || recipeRemovesContinuum.value) return null
  try {
    const start = parseBound(state.continuum.start, 'from')
    const stop = parseBound(state.continuum.stop, 'to')
    return { op: 'continuum_removal', params: { start, stop } }
  } catch (err) {
    state.continuumError = (err as Error).message
    return null
  }
}

export function activeSteps(): StepPayload[] {
  const steps = state.steps.filter((s) => s.enabled).map((s) => ({ op: s.op, params: { ...s.params } }))
  const cr = continuumStep()
  return cr ? [...steps, cr] : steps
}

export function recipeDocument() {
  return {
    name: state.recipeName,
    description: '',
    steps: activeSteps().map((s) => ({ op: s.op, ...s.params })),
  }
}

const continuumKey = () => JSON.stringify(state.continuum) + String(recipeRemovesContinuum.value)

export async function loadRecipe(file: File) {
  try {
    const parsed = await api.parseRecipe(await file.text(), file.name)
    state.steps = []
    for (const s of parsed.steps) addStep(s.op, s.params)
    for (const s of state.steps) s.open = false
    state.recipeName = parsed.name || file.name.replace(/\.(toml|json)$/i, '')
    notify(`Recipe "${state.recipeName}" loaded (${parsed.steps.length} steps)`, 'success')
  } catch (err) {
    notify(message(err))
  }
}

// --- processing (debounced, latest request wins) -----------------------------------------

let processSeq = 0
let processTimer: number | undefined

async function runProcess() {
  const seq = ++processSeq
  const ids = visibleIds.value
  const enabled = state.steps.filter((s) => s.enabled)
  const steps = activeSteps()
  for (const s of state.steps) s.serverErrors = {}
  if (!ids.length || !steps.length) {
    state.processed = {}
    state.processErrors = []
    return
  }
  if (enabled.some((s) => Object.keys(s.localErrors).length)) {
    state.processErrors = ['Fix the highlighted parameters to update the result.']
    return
  }
  state.processing = true
  try {
    const r = await api.process(ids, steps)
    if (seq !== processSeq) return
    state.processed = Object.fromEntries(r.results.map((x) => [x.id, x]))
    state.processErrors = r.errors.map((e) => {
      const names = e.ids.map((id) => state.spectra.find((s) => s.id === id)?.name ?? id)
      return `${names.join(', ')}: ${e.message}`
    })
  } catch (err) {
    if (seq !== processSeq) return
    state.processed = {}
    if (err instanceof ApiError && err.status === 422 && isStepDetail(err.detail)) {
      for (const p of err.detail.steps) {
        const step = enabled[p.step]
        if (!step) {
          state.continuumError = p.errors.map((e) => e.msg).join('; ')
          continue
        }
        for (const e of p.errors) step.serverErrors[String(e.loc[0] ?? '_')] = e.msg
        step.open = true
      }
      state.processErrors = ['Some steps have invalid parameters.']
    } else state.processErrors = [message(err)]
  } finally {
    if (seq === processSeq) state.processing = false
  }
}

function isStepDetail(d: unknown): d is { steps: StepProblem[] } {
  return typeof d === 'object' && d !== null && Array.isArray((d as { steps?: unknown }).steps)
}

export function scheduleProcess() {
  window.clearTimeout(processTimer)
  processTimer = window.setTimeout(runProcess, 250)
}

watch(
  () => [
    visibleIds.value.join(','),
    JSON.stringify(state.steps.map((s) => [s.op, s.enabled, s.params, s.localErrors])),
    continuumKey(),
  ],
  scheduleProcess,
)

// --- QC ----------------------------------------------------------------------------------

let qcSeq = 0
let qcTimer: number | undefined

async function runQc() {
  const seq = ++qcSeq
  const ids = visibleIds.value
  state.qcServerErrors = {}
  if (!ids.length) {
    state.qcResults = []
    state.qcErrors = []
    return
  }
  if (Object.keys(state.qcLocalErrors).length) return
  try {
    const r = await api.qc(ids, state.qcParams)
    if (seq !== qcSeq) return
    state.qcResults = r.results
    state.qcErrors = r.errors.map((e) => e.message)
  } catch (err) {
    if (seq !== qcSeq) return
    const d = err instanceof ApiError ? (err.detail as { params?: { loc: unknown[]; msg: string }[] }) : null
    if (d && Array.isArray(d.params))
      for (const e of d.params) state.qcServerErrors[String(e.loc[0] ?? '_')] = e.msg
    else state.qcErrors = [message(err)]
  }
}

watch(
  () => [visibleIds.value.join(','), JSON.stringify(state.qcParams), JSON.stringify(state.qcLocalErrors)],
  () => {
    window.clearTimeout(qcTimer)
    qcTimer = window.setTimeout(runQc, 300)
  },
)

// --- export ------------------------------------------------------------------------------

export async function exportCsv() {
  const ids = visibleIds.value
  if (!ids.length) return notify('Nothing to export: no spectrum is shown.')
  try {
    const text = await api.exportCsv(ids, activeSteps())
    download(new Blob([text], { type: 'text/csv' }), 'swirl_export.csv')
  } catch (err) {
    notify(message(err))
  }
}

export function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// --- band parameters (measured on the recipe output) --------------------------------------

export const bandDefinitions = computed(
  () => (state.bandParams.bands as BandDefinition[] | undefined) ?? [],
)

let bandSeq = 0
let bandTimer: number | undefined

async function runBands() {
  const seq = ++bandSeq
  const ids = visibleIds.value
  state.bandServerErrors = {}
  if (!ids.length || !bandDefinitions.value.length) {
    state.bandRows = []
    state.bandErrors = []
    return
  }
  if (Object.keys(state.bandLocalErrors).length) return
  if (state.steps.some((s) => s.enabled && Object.keys(s.localErrors).length)) return
  state.bandBusy = true
  try {
    const r = await api.bands(ids, activeSteps(), state.bandParams)
    if (seq !== bandSeq) return
    state.bandRows = r.rows
    state.bandErrors = r.errors.map((e) => e.message)
  } catch (err) {
    if (seq !== bandSeq) return
    state.bandRows = []
    const d = err instanceof ApiError ? (err.detail as { params?: { loc: unknown[]; msg: string }[]; steps?: unknown }) : null
    if (d && Array.isArray(d.params)) {
      for (const e of d.params) state.bandServerErrors[String(e.loc[0] ?? '_')] = e.msg
      state.bandErrors = d.params.map((e) => `${e.loc.join('.')}: ${e.msg}`)
    } else if (d && d.steps) state.bandErrors = ['Fix the recipe parameters first.']
    else state.bandErrors = [message(err)]
  } finally {
    if (seq === bandSeq) state.bandBusy = false
  }
}

watch(
  () => [
    visibleIds.value.join(','),
    JSON.stringify(state.steps.map((s) => [s.op, s.enabled, s.params, s.localErrors])),
    JSON.stringify(state.bandParams),
    JSON.stringify(state.bandLocalErrors),
    continuumKey(),
  ],
  () => {
    window.clearTimeout(bandTimer)
    bandTimer = window.setTimeout(runBands, 300)
  },
)

export function addBand() {
  const bands = [...bandDefinitions.value]
  let n = bands.length + 1
  while (bands.some((b) => b.name === `band${n}`)) n++
  bands.push({ name: `band${n}`, center: 2200, lo: 2180, hi: 2220 })
  state.bandParams.bands = bands
}

export function updateBand(index: number, patch: Partial<BandDefinition>) {
  const bands = bandDefinitions.value.map((b, i) => (i === index ? { ...b, ...patch } : b))
  const old = bandDefinitions.value[index]
  state.bandParams.bands = bands
  // Keep ratios consistent when a band is renamed.
  if (patch.name && patch.name !== old.name) {
    const ratios = (state.bandParams.ratios as [string, string][] | undefined) ?? []
    state.bandParams.ratios = ratios.map(([a, b]) => [a === old.name ? patch.name! : a, b === old.name ? patch.name! : b])
  }
}

export function removeBand(index: number) {
  const name = bandDefinitions.value[index].name
  state.bandParams.bands = bandDefinitions.value.filter((_, i) => i !== index)
  const ratios = (state.bandParams.ratios as [string, string][] | undefined) ?? []
  state.bandParams.ratios = ratios.filter(([a, b]) => a !== name && b !== name)
}

export function resetBands() {
  if (state.bandSchema) state.bandParams = defaults(state.bandSchema)
  state.bandLocalErrors = {}
}

export async function exportBands() {
  const ids = visibleIds.value
  if (!ids.length) return notify('Nothing to export: no spectrum is shown.')
  try {
    const text = await api.bandsExport(ids, activeSteps(), state.bandParams)
    download(new Blob([text], { type: 'text/csv' }), 'swirl_bands.csv')
  } catch (err) {
    notify(message(err))
  }
}

// --- drill holes -----------------------------------------------------------------------------

export async function refreshHoles() {
  try {
    state.holes = await api.holes()
  } catch (err) {
    notify(message(err))
    return
  }
  if (!state.holes.some((h) => h.hole_id === state.selectedHole))
    state.selectedHole = state.holes[0]?.hole_id ?? null
  if (!state.selectedHole) state.log = null
}

export async function loadExampleHole() {
  state.busy = true
  try {
    const r = await api.exampleHole()
    addLoaded(r.added, r.errors)
    await refreshHoles()
    state.selectedHole = r.added[0]?.hole_id ?? state.selectedHole
    state.mainView = 'drillhole'
  } catch (err) {
    notify(message(err))
  } finally {
    state.busy = false
  }
}

let logSeq = 0
let logTimer: number | undefined

async function runLog() {
  const seq = ++logSeq
  if (state.mainView !== 'drillhole' || !state.selectedHole) return
  if (state.steps.some((s) => s.enabled && Object.keys(s.localErrors).length)) return
  if (Object.keys(state.bandLocalErrors).length || Object.keys(state.qcLocalErrors).length) return
  state.logBusy = true
  try {
    const log = await api.log({
      hole_id: state.selectedHole,
      steps: activeSteps(),
      band_params: state.bandParams,
      qc_params: state.qcParams,
    })
    if (seq !== logSeq) return
    state.log = log
    state.logErrors = log.notes
  } catch (err) {
    if (seq !== logSeq) return
    state.logErrors = [message(err)]
  } finally {
    if (seq === logSeq) state.logBusy = false
  }
}

watch(
  () => [
    state.mainView,
    state.selectedHole,
    state.spectra.length,
    JSON.stringify(state.steps.map((s) => [s.op, s.enabled, s.params, s.localErrors])),
    JSON.stringify(state.bandParams),
    JSON.stringify(state.qcParams),
    continuumKey(),
  ],
  () => {
    window.clearTimeout(logTimer)
    logTimer = window.setTimeout(runLog, 300)
  },
)
