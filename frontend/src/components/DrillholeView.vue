<script setup lang="ts">
// Strip log of one hole: every track shares the depth axis. Everything shown is computed
// server-side (recipe output, band parameters, QC); this component only draws it.
import { mdiChartBellCurve } from '@mdi/js'
import Plotly from 'plotly.js-dist-min'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useTheme } from 'vuetify'

import { SERIES, STATUS } from '../palette'
import { setVisible, state } from '../store'

interface Track {
  key: string
  label: string
  width: number
}

const QTY: Record<string, string> = {
  reflectance: 'Reflectance',
  continuum_removed: 'Hull quotient',
  raw: 'Raw DN',
}
const MINERAL_ORDER = ['white_mica', 'illite', 'chlorite', 'hematite']
const QC_SHORT: Record<string, string> = {
  above_max: 'max',
  low_albedo: 'albedo',
  missing_bands: 'gaps',
  noisy: 'noise',
  splice_step: 'splice',
}
const DEFAULT_TRACKS = [
  'truth',
  'image',
  'albedo',
  'band:AlOH:position',
  'band:AlOH:depth',
  'band:FeOH:depth',
  'band:MgOH:depth',
  'qc',
]

const el = ref<HTMLDivElement | null>(null)
const theme = useTheme()
const dark = computed(() => theme.current.value.dark)
let observer: ResizeObserver | undefined
let clickBound = false

const available = computed<Track[]>(() => {
  const log = state.log
  if (!log) return []
  const t: Track[] = []
  if (log.truth) t.push({ key: 'truth', label: 'Composition (truth)', width: 1.3 })
  t.push({ key: 'image', label: `${QTY[log.quantity] ?? log.quantity} image`, width: 3 })
  t.push({ key: 'albedo', label: 'Mean reflectance', width: 1 })
  for (const b of Object.keys(log.bands)) {
    t.push({ key: `band:${b}:position`, label: `${b} position (nm)`, width: 1 })
    t.push({ key: `band:${b}:depth`, label: `${b} depth`, width: 1 })
    t.push({ key: `band:${b}:width`, label: `${b} width (nm)`, width: 1 })
  }
  for (const r of Object.keys(log.ratios)) t.push({ key: `ratio:${r}`, label: r, width: 1 })
  if (log.qc) t.push({ key: 'qc', label: 'QC flags', width: 1 })
  return t
})

// First time a log arrives, show the default tracks that exist.
watch(available, (tracks) => {
  if (!state.logTracks.length && tracks.length)
    state.logTracks = DEFAULT_TRACKS.filter((k) => tracks.some((t) => t.key === k))
})

const shown = computed(() =>
  state.logTracks.map((k) => available.value.find((t) => t.key === k)).filter((t): t is Track => !!t),
)

const mid = computed(() =>
  (state.log?.depth_from ?? []).map((a, i) => {
    const b = state.log!.depth_to[i]
    return a == null || b == null ? null : (a + b) / 2
  }),
)

const focusedIndex = computed(() => (state.log && state.focused ? state.log.ids.indexOf(state.focused) : -1))

const figure = computed(() => {
  const log = state.log
  if (!log) return { traces: [], layout: {} }
  const ink = dark.value ? '#ffffff' : '#0b0b0b'
  const muted = dark.value ? '#c3c2b7' : '#52514e'
  const grid = dark.value ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.07)'
  const line = dark.value ? SERIES.dark[0] : SERIES.light[0]
  const y = mid.value
  const ids = log.ids
  const traces: unknown[] = []
  const layout: Record<string, unknown> = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: ink, size: 11, family: 'Roboto, system-ui, sans-serif' },
    margin: { l: 60, r: 12, t: 58, b: 40 },
    hovermode: 'closest',
    hoverlabel: { bgcolor: dark.value ? '#262625' : '#ffffff', font: { color: ink } },
    showlegend: !!log.truth && state.logTracks.includes('truth'),
    legend: { orientation: 'h', x: 0, y: -0.02, yanchor: 'top', font: { color: muted, size: 10 } },
    uirevision: log.hole_id,
    yaxis: {
      title: { text: 'Depth (m)' },
      autorange: 'reversed',
      gridcolor: grid,
      zeroline: false,
      color: muted,
      showspikes: true,
      spikemode: 'across',
      spikesnap: 'cursor',
      spikethickness: 1,
      spikecolor: muted,
      spikedash: 'dot',
    },
    shapes: [] as unknown[],
  }

  const total = shown.value.reduce((s, t) => s + t.width, 0) || 1
  const gap = 0.018
  let x0 = 0
  shown.value.forEach((track, i) => {
    const w = (track.width / total) * (1 - gap * (shown.value.length - 1))
    const axisName = i === 0 ? 'xaxis' : `xaxis${i + 1}`
    const xref = i === 0 ? 'x' : `x${i + 1}`
    layout[axisName] = {
      domain: [x0, x0 + w],
      anchor: 'y',
      side: 'top',
      title: { text: track.label, font: { size: 10, color: ink }, standoff: 4 },
      gridcolor: grid,
      zeroline: false,
      color: muted,
      tickfont: { size: 9 },
      nticks: 4,
    }
    x0 += w + gap
    const custom = ids
    const base = { xaxis: xref, yaxis: 'y', customdata: custom }

    if (track.key === 'image') {
      const vals = log.image.values.flat().filter((v): v is number => v != null).sort((a, b) => a - b)
      const zmin = vals.length ? vals[Math.floor(0.02 * (vals.length - 1))] : 0
      const zmax = log.quantity === 'continuum_removed' ? 1 : vals.length ? vals[Math.floor(0.99 * (vals.length - 1))] : 1
      traces.push({
        ...base,
        type: 'heatmap',
        x: log.image.wavelength,
        y,
        z: log.image.values,
        zmin,
        zmax,
        // Sequential single hue: deeper absorption (lower value) = darker.
        colorscale: [
          [0, '#0d366b'],
          [0.35, '#256abf'],
          [0.7, '#86b6ef'],
          [1, dark.value ? '#e8f1fc' : '#f4f8fd'],
        ],
        showscale: false,
        customdata: ids.map((id) => log.image.wavelength.map(() => id)),
        hovertemplate: '%{y:.1f} m · %{x:.0f} nm: %{z:.3f}<extra></extra>',
      })
      ;(layout[axisName] as Record<string, unknown>).title = {
        text: `${track.label} (nm)`,
        font: { size: 10, color: ink },
        standoff: 4,
      }
    } else if (track.key === 'truth' && log.truth) {
      const keys = [...MINERAL_ORDER.filter((k) => k in log.truth!.composition), ...Object.keys(log.truth.composition).filter((k) => !MINERAL_ORDER.includes(k))]
      const palette = dark.value ? SERIES.dark : SERIES.light
      keys.forEach((k, j) => {
        traces.push({
          ...base,
          type: 'scatter',
          mode: 'lines',
          orientation: 'h',
          stackgroup: 'truth',
          x: log.truth!.composition[k],
          y,
          name: k.replace('_', ' '),
          line: { width: 0.5, color: palette[j % 8] },
          fillcolor: palette[j % 8],
          hovertemplate: `${k.replace('_', ' ')}: %{x:.2f}<extra></extra>`,
        })
      })
      ;(layout[axisName] as Record<string, unknown>).range = [0, 1]
    } else if (track.key === 'albedo') {
      traces.push({
        ...base,
        type: 'scatter',
        mode: 'lines',
        x: log.mean_reflectance,
        y,
        line: { color: line, width: 1.5 },
        showlegend: false,
        hovertemplate: '%{y:.1f} m: %{x:.3f}<extra></extra>',
      })
    } else if (track.key.startsWith('band:')) {
      const [, band, measure] = track.key.split(':')
      const series = log.bands[band]
      const values = series[measure as 'position' | 'depth' | 'width']
      const status = series.status
      traces.push({
        ...base,
        type: 'scatter',
        mode: 'lines+markers',
        x: values.map((v, k) => (status[k] === 'minimum' || status[k] === 'shoulder' ? v : null)),
        y,
        line: { color: line, width: 1.2 },
        marker: {
          size: 5,
          color: line,
          symbol: status.map((st) => (st === 'shoulder' ? 'circle-open' : 'circle')),
        },
        showlegend: false,
        text: status,
        hovertemplate: `%{y:.1f} m: %{x:.${measure === 'depth' ? 3 : 1}f} (%{text})<extra></extra>`,
      })
      const truth = log.truth?.aloh_center
      if (measure === 'position' && truth) {
        // Overlay the generating white-mica AlOH centre when it falls in this band's range.
        const finite = values.filter((v): v is number => v != null)
        const lo = Math.min(...finite)
        const hi = Math.max(...finite)
        const inRange = truth.some((t) => t != null && t >= lo - 10 && t <= hi + 10)
        if (inRange && band === 'AlOH')
          traces.push({
            ...base,
            type: 'scatter',
            mode: 'lines',
            x: truth,
            y,
            line: { color: muted, width: 1.5, dash: 'dash' },
            showlegend: false,
            hovertemplate: 'truth (white mica): %{x:.1f} nm<extra></extra>',
          })
      }
    } else if (track.key.startsWith('ratio:')) {
      const name = track.key.slice(6)
      traces.push({
        ...base,
        type: 'scatter',
        mode: 'lines',
        x: log.ratios[name],
        y,
        line: { color: line, width: 1.2 },
        showlegend: false,
        hovertemplate: `%{y:.1f} m: %{x:.3f}<extra></extra>`,
      })
    } else if (track.key === 'qc' && log.qc) {
      // One column per flag type, so a common flag does not hide the rare ones.
      const xs: string[] = []
      const ys: (number | null)[] = []
      const cd: string[] = []
      log.qc.forEach((flags, k) => {
        for (const f of flags) {
          xs.push(QC_SHORT[f] ?? f)
          ys.push(y[k])
          cd.push(ids[k])
        }
      })
      traces.push({
        xaxis: xref,
        yaxis: 'y',
        type: 'scatter',
        mode: 'markers',
        x: xs,
        y: ys,
        customdata: cd,
        marker: { symbol: 'line-ew', size: 9, line: { width: 2, color: STATUS.serious } },
        showlegend: false,
        hovertemplate: '%{y:.1f} m: %{x}<extra></extra>',
      })
      const flagged = log.qc.filter((f) => f.length > 0).length
      Object.assign(layout[axisName] as object, {
        type: 'category',
        categoryorder: 'array',
        categoryarray: Object.values(QC_SHORT),
        range: [-0.5, Object.keys(QC_SHORT).length - 0.5],
        tickangle: -90,
        tickfont: { size: 8 },
        showgrid: true,
        title: { text: `QC (${flagged} flagged)`, font: { size: 10, color: ink }, standoff: 4 },
      })
    }
  })

  if (focusedIndex.value >= 0) {
    const d = y[focusedIndex.value]
    ;(layout.shapes as unknown[]).push({
      type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: d, y1: d,
      line: { color: dark.value ? '#eda100' : '#b87800', width: 1.5 },
    })
  }
  return { traces, layout }
})

async function render() {
  if (!el.value) return
  const { traces, layout } = figure.value
  await Plotly.react(el.value, traces, layout, {
    responsive: true,
    displaylogo: false,
    // Local data never leaves the machine: no Chart Studio / cloud buttons.
    showSendToCloud: false,
    showEditInChartStudio: false,
    showLink: false,
    modeBarButtonsToRemove: ['lasso2d', 'select2d', 'sendDataToCloud', 'editInChartStudio'],
    toImageButtonOptions: { format: 'png', filename: `swirl_log_${state.log?.hole_id ?? ''}`, scale: 2 },
  })
  if (!clickBound && el.value) {
    clickBound = true
    ;(el.value as unknown as { on: (ev: string, cb: (e: { points: { customdata?: unknown; y?: number }[] }) => void) => void }).on(
      'plotly_click',
      (e) => {
        const p = e.points[0]
        const id = typeof p?.customdata === 'string' ? p.customdata : null
        if (id) state.focused = id
      },
    )
  }
}

function showSpectrum() {
  if (!state.focused) return
  setVisible(state.focused, true)
  state.mainView = 'spectra'
}

const focusedName = computed(() => (focusedIndex.value >= 0 ? state.log!.names[focusedIndex.value] : null))

watch(figure, render)
onMounted(() => {
  void render()
  observer = new ResizeObserver(() => el.value && Plotly.Plots.resize(el.value))
  if (el.value) observer.observe(el.value)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  if (el.value) Plotly.purge(el.value)
})
</script>

<template>
  <div class="d-flex flex-column h-100">
    <div class="d-flex align-center ga-3 px-3 py-2 border-b flex-wrap">
      <v-select
        v-model="state.selectedHole"
        :items="state.holes.map((h) => ({ title: `${h.hole_id} (${h.n} samples, ${h.top}–${h.bottom} m)`, value: h.hole_id }))"
        label="Hole"
        style="max-width: 320px"
        :disabled="!state.holes.length"
      />
      <v-select
        v-model="state.logTracks"
        :items="available.map((t) => ({ title: t.label, value: t.key }))"
        label="Tracks"
        multiple
        chips
        closable-chips
        style="min-width: 320px; flex: 1"
      />
      <v-progress-circular v-if="state.logBusy" indeterminate size="16" width="2" />
      <template v-if="focusedName">
        <span class="text-caption mono">{{ focusedName }}</span>
        <v-btn :prepend-icon="mdiChartBellCurve" size="small" variant="tonal" @click="showSpectrum">Show spectrum</v-btn>
      </template>
    </div>
    <v-alert v-for="(e, k) in state.logErrors" :key="k" type="info" variant="tonal" density="compact" class="mx-3 mt-2 text-caption">
      {{ e }}
    </v-alert>
    <div class="position-relative flex-grow-1" style="min-height: 0">
      <div ref="el" class="h-100 w-100" />
      <div v-if="!state.holes.length" class="position-absolute d-flex flex-column align-center justify-center text-muted text-center pa-6 ga-3" style="inset: 0">
        <div>No drill hole yet: the spectra have no hole and depth.</div>
        <v-btn color="primary" variant="tonal" @click="state.holesDialog = true">Assign holes &amp; depths…</v-btn>
        <div class="text-caption">Read them from the file names by example, or from a sample table.</div>
      </div>
    </div>
  </div>
</template>
