// Application state. Everything computed (processing, QC) comes back from the API; this
// module only keeps what the user chose and what the server returned.

import { computed, markRaw, reactive, watch } from 'vue'

import {
  api,
  ApiError,
  type BandDefinition,
  type BandRow,
  type HoleInfo,
  type HoleLogData,
  type JsonSchema,
  type OpenedProject,
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
  // Band markers need band parameters for every shown spectrum: off unless asked for.
  showBandMarkers: false,
  // Bottom panel: QC and band parameters are computed only while their tab is shown.
  bottomTab: 'qc' as 'qc' | 'bands' | 'details',
  bottomOpen: true,
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
  project: { name: '', created: null as string | null, dirty: false },
  holesDialog: false,
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
  if (on) assignSlot(id)
  else releaseSlot(id)
}

export function setAllVisible(on: boolean) {
  for (const s of state.spectra) setVisible(s.id, on)
}

/** Store server data outside Vue's reactivity: the arrays are only drawn, never edited,
 * and wrapping them in proxies makes every read (Plotly's included) slow. */
function keepInput(d: SpectrumDetail) {
  state.inputs[d.id] = markRaw(d)
}

// --- workspace ---------------------------------------------------------------------------

export async function init() {
  restoring = true
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
  } finally {
    setTimeout(() => {
      restoring = false
      state.project.dirty = false
    }, 0)
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
  if (state.mainView !== 'spectra') {
    state.processing = false
    return
  }
  const ids = visibleIds.value
  const missing = ids.filter((id) => !state.inputs[id])
  const enabled = state.steps.filter((s) => s.enabled)
  const steps = activeSteps()
  for (const s of state.steps) s.serverErrors = {}
  const blocked = enabled.some((s) => Object.keys(s.localErrors).length)
  if (!ids.length || !steps.length || blocked) {
    state.processed = {}
    state.processErrors = blocked ? ['Fix the highlighted parameters to update the result.'] : []
    try {
      if (missing.length) {
        const data = await api.spectraData(missing)
        if (seq === processSeq) data.forEach(keepInput)
      }
    } catch (err) {
      notify(message(err))
    } finally {
      if (seq === processSeq) state.processing = false
    }
    return
  }
  state.processing = true
  try {
    // One request: the processed spectra plus the inputs not loaded yet.
    const r = await api.process(ids, steps, missing)
    if (seq !== processSeq) return
    r.inputs.forEach(keepInput)
    state.processed = Object.fromEntries(r.results.map((x) => [x.id, markRaw(x)]))
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
  // Counts as processing from now: the plot waits for the answer instead of redrawing the
  // stale state during the debounce.
  if (state.mainView === 'spectra') state.processing = true
  processTimer = window.setTimeout(runProcess, 250)
}

watch(
  () => [
    state.mainView,
    visibleIds.value.join(','),
    JSON.stringify(state.steps.map((s) => [s.op, s.enabled, s.params, s.localErrors])),
    continuumKey(),
  ],
  scheduleProcess,
)

// --- QC ----------------------------------------------------------------------------------

let qcSeq = 0
let qcTimer: number | undefined

const qcShown = () => state.bottomOpen && state.bottomTab === 'qc'

async function runQc() {
  const seq = ++qcSeq
  if (!qcShown()) return
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
  () => [qcShown(), visibleIds.value.join(','), JSON.stringify(state.qcParams), JSON.stringify(state.qcLocalErrors)],
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

const bandsNeeded = () =>
  (state.bottomOpen && state.bottomTab === 'bands') || (state.showBandMarkers && state.mainView === 'spectra')

async function runBands() {
  const seq = ++bandSeq
  if (!bandsNeeded()) return
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
    state.bandRows = r.rows.map((row) => markRaw(row))
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
    bandsNeeded(),
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
    state.log = markRaw(log)
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

// --- projects ------------------------------------------------------------------------------

let restoring = false

function settingsSnapshot() {
  return {
    recipe: {
      name: state.recipeName,
      steps: state.steps.map((s) => ({ op: s.op, params: { ...s.params }, enabled: s.enabled })),
    },
    continuum: { ...state.continuum },
    band_params: state.bandParams,
    qc_params: state.qcParams,
    ui: {
      main_view: state.mainView,
      view_mode: state.viewMode,
      selected_hole: state.selectedHole,
      log_tracks: state.logTracks,
      show_band_markers: state.showBandMarkers,
      show_band_windows: state.showBandWindows,
    },
  }
}

// Anything saved in a project marks it modified.
watch(
  () => [JSON.stringify(settingsSnapshot()), state.spectra.length, visibleIds.value.join(',')],
  () => {
    if (!restoring) state.project.dirty = true
  },
)

window.addEventListener('beforeunload', (e) => {
  if (state.project.dirty && state.spectra.length) {
    e.preventDefault()
    e.returnValue = ''
  }
})

export async function saveProject() {
  const name = state.project.name || 'project'
  try {
    const blob = await api.saveProject({
      name,
      created: state.project.created,
      settings: settingsSnapshot(),
      visible_ids: visibleIds.value,
      focused_id: state.focused,
    })
    download(blob, `${name.replace(/[^\w.-]+/g, '_')}.swirl`)
    state.project.name = name
    state.project.created ??= new Date().toISOString()
    state.project.dirty = false
    notify(`Project "${name}" saved (${state.spectra.length} spectra)`, 'success')
  } catch (err) {
    notify(message(err))
  }
}

function applyProject(p: OpenedProject) {
  const st = p.settings as Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any
  state.spectra = p.spectra
  state.visible = {}
  state.slots = {}
  state.inputs = {}
  state.processed = {}
  state.bandRows = []
  state.log = null
  for (const id of p.visible_ids) setVisible(id, true)
  for (const s of p.spectra) if (!state.visible[s.id]) state.visible[s.id] = false
  state.focused = p.focused_id

  state.steps = []
  for (const step of st.recipe?.steps ?? []) {
    if (!state.operations.some((o) => o.name === step.op)) continue
    addStep(step.op, { ...(step.params ?? {}) })
    state.steps[state.steps.length - 1].enabled = step.enabled !== false
  }
  for (const s of state.steps) s.open = false
  state.recipeName = st.recipe?.name ?? ''
  state.continuum = { on: true, start: '', stop: '', ...(st.continuum ?? {}) }
  if (state.bandSchema) state.bandParams = { ...defaults(state.bandSchema), ...(st.band_params ?? {}) }
  if (state.qcSchema) state.qcParams = { ...defaults(state.qcSchema), ...(st.qc_params ?? {}) }
  state.bandLocalErrors = {}
  state.qcLocalErrors = {}
  const ui = st.ui ?? {}
  state.mainView = ui.main_view === 'drillhole' ? 'drillhole' : 'spectra'
  state.viewMode = ui.view_mode ?? 'both'
  state.logTracks = ui.log_tracks ?? []
  state.showBandMarkers = ui.show_band_markers ?? false
  state.showBandWindows = ui.show_band_windows ?? true
  state.project = { name: p.name, created: p.created || null, dirty: false }
  return ui.selected_hole as string | null | undefined
}

export async function openProject(file: File) {
  if (state.project.dirty && state.spectra.length && !window.confirm('Discard the unsaved changes of the current project?'))
    return
  state.busy = true
  restoring = true
  try {
    const p = await api.openProject(file)
    const hole = applyProject(p)
    await refreshHoles()
    if (hole && state.holes.some((h) => h.hole_id === hole)) state.selectedHole = hole
    notify(
      p.warnings.length ? `Project opened with warnings:\n${p.warnings.join('\n')}` : `Project "${p.name}" opened`,
      p.warnings.length ? 'warning' : 'success',
    )
  } catch (err) {
    notify(message(err))
  } finally {
    state.busy = false
    // Let the watchers settle on the restored state before tracking changes again.
    setTimeout(() => {
      restoring = false
      state.project.dirty = false
    }, 0)
  }
}

export async function newProject() {
  if (state.project.dirty && state.spectra.length && !window.confirm('Discard the unsaved changes of the current project?'))
    return
  restoring = true
  await clearWorkspace()
  state.steps = []
  state.recipeName = ''
  state.continuum = { on: true, start: '', stop: '' }
  if (state.bandSchema) state.bandParams = defaults(state.bandSchema)
  if (state.qcSchema) state.qcParams = defaults(state.qcSchema)
  state.logTracks = []
  state.mainView = 'spectra'
  state.project = { name: '', created: null, dirty: false }
  setTimeout(() => {
    restoring = false
    state.project.dirty = false
  }, 0)
}

// --- hole / depth assignment ----------------------------------------------------------------

export async function loadExampleNamed() {
  state.busy = true
  try {
    const r = await api.exampleNamed()
    addLoaded(r.added, r.errors)
    state.holesDialog = true
  } catch (err) {
    notify(message(err))
  } finally {
    state.busy = false
  }
}

/** Take the server's updated summaries after hole/depth metadata changed. */
export async function spectraUpdated(spectra: SpectrumSummary[], text: string) {
  const changed = new Set(
    spectra
      .filter((s) => {
        const old = state.spectra.find((o) => o.id === s.id)
        return !old || old.hole_id !== s.hole_id || old.depth_from !== s.depth_from
      })
      .map((s) => s.id),
  )
  state.spectra = spectra
  for (const id of changed) delete state.inputs[id]
  const refetch = [...changed].filter((id) => state.visible[id])
  if (refetch.length) void api.spectraData(refetch).then((data) => data.forEach(keepInput))
  await refreshHoles()
  notify(text, 'success')
}
