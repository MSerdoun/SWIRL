// Application state. Everything computed (processing, QC) comes back from the API; this
// module only keeps what the user chose and what the server returned.

import { computed, reactive, watch } from 'vue'

import {
  api,
  ApiError,
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
    const [health, ops, spectra, qcSchema] = await Promise.all([
      api.health(),
      api.operations(),
      api.spectra(),
      api.qcSchema(),
    ])
    state.version = health.version
    state.operations = ops
    state.qcSchema = qcSchema
    state.qcParams = defaults(qcSchema)
    state.spectra = spectra
    for (const s of spectra.slice(0, 8)) setVisible(s.id, true)
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

export function activeSteps(): StepPayload[] {
  return state.steps.filter((s) => s.enabled).map((s) => ({ op: s.op, params: { ...s.params } }))
}

export function recipeDocument() {
  return {
    name: state.recipeName,
    description: '',
    steps: state.steps.filter((s) => s.enabled).map((s) => ({ op: s.op, ...s.params })),
  }
}

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
  for (const s of state.steps) s.serverErrors = {}
  if (!ids.length || !enabled.length) {
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
    const r = await api.process(ids, activeSteps())
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
        if (!step) continue
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
  () => [visibleIds.value.join(','), JSON.stringify(state.steps.map((s) => [s.op, s.enabled, s.params, s.localErrors]))],
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
