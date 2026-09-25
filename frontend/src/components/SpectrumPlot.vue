<script setup lang="ts">
import Plotly from 'plotly.js-dist-min'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useTheme } from 'vuetify'

import { seriesColor } from '../palette'
import { bandDefinitions, state, visibleIds } from '../store'

const Y_TITLE: Record<string, string> = {
  reflectance: 'Reflectance',
  continuum_removed: 'Hull quotient',
  raw: 'Raw DN',
}

const el = ref<HTMLDivElement | null>(null)
const theme = useTheme()
const dark = computed(() => theme.current.value.dark)
let observer: ResizeObserver | undefined

function interp(xs: (number | null)[], ys: (number | null)[], x: number): number | null {
  let lo = 0
  let hi = xs.length - 1
  if (xs[lo] == null || xs[hi] == null || x < (xs[lo] as number) || x > (xs[hi] as number)) return null
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if ((xs[mid] as number) <= x) lo = mid
    else hi = mid
  }
  const [x0, x1, y0, y1] = [xs[lo], xs[hi], ys[lo], ys[hi]] as number[]
  if (y0 == null || y1 == null) return null
  return x1 === x0 ? y0 : y0 + ((x - x0) / (x1 - x0)) * (y1 - y0)
}

const hasProcessed = computed(() => visibleIds.value.some((id) => state.processed[id]))
const mode = computed(() => (hasProcessed.value ? state.viewMode : 'input'))

function quantityOf(list: { quantity: string }[]): string {
  const qs = [...new Set(list.map((x) => x.quantity))]
  return qs.length === 1 ? qs[0] : 'mixed'
}

const figure = computed(() => {
  const ids = visibleIds.value
  const inputs = ids.map((id) => state.inputs[id]).filter(Boolean)
  const outputs = ids.map((id) => state.processed[id]).filter(Boolean)
  const qIn = quantityOf(inputs)
  const qOut = quantityOf(outputs)
  const m = mode.value
  // Different quantities never share an axis: stack two plots on a common wavelength axis.
  const stacked = m === 'both' && outputs.length > 0 && qIn !== qOut
  const overlay = m === 'both' && !stacked
  const ink = dark.value ? '#ffffff' : '#0b0b0b'
  const muted = dark.value ? '#c3c2b7' : '#52514e'
  const grid = dark.value ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.07)'

  const traces: unknown[] = []
  for (const id of ids) {
    const color = seriesColor(state.slots[id], dark.value)
    const focused = state.focused === id
    const width = focused ? 3 : 1.8
    const input = state.inputs[id]
    const output = state.processed[id]
    if (input && (m === 'input' || m === 'both')) {
      traces.push({
        type: 'scatter',
        mode: 'lines',
        x: input.wavelength,
        y: input.values,
        name: input.name,
        legendgroup: id,
        showlegend: true,
        line: { color, width: overlay && output ? 1.2 : width },
        opacity: overlay && output ? 0.4 : 1,
        xaxis: 'x',
        yaxis: 'y',
        hovertemplate: `${input.name}${overlay && output ? ' (input)' : ''}: %{y:.4f}<extra></extra>`,
      })
    }
    if (output && (m === 'processed' || m === 'both')) {
      traces.push({
        type: 'scatter',
        mode: 'lines',
        x: output.wavelength,
        y: output.values,
        name: output.name,
        legendgroup: id,
        showlegend: m === 'processed' || !input,
        line: { color, width },
        xaxis: 'x',
        yaxis: stacked ? 'y2' : 'y',
        hovertemplate: `${output.name}${m === 'both' ? ' (processed)' : ''}: %{y:.4f}<extra></extra>`,
      })
    }
  }

  // Band markers: on the processed curve when shown, else on the input curve.
  if (state.showBandMarkers) {
    for (const row of state.bandRows) {
      if (!ids.includes(row.id)) continue
      const onOutput = !!state.processed[row.id] && m !== 'input'
      const curve = onOutput ? state.processed[row.id] : state.inputs[row.id]
      if (!curve) continue
      const xs: number[] = []
      const ys: number[] = []
      const text: string[] = []
      for (const [band, meas] of Object.entries(row.bands)) {
        if (meas.position == null || (meas.status !== 'minimum' && meas.status !== 'shoulder')) continue
        const y = interp(curve.wavelength, curve.values, meas.position)
        if (y == null) continue
        xs.push(meas.position)
        ys.push(y)
        const t = row.truth?.[band]
        text.push(
          `${row.name} · ${band} (${meas.status})<br>${meas.position.toFixed(2)} nm · depth ${meas.depth?.toFixed(3)}` +
            (t ? `<br>truth ${t.center} nm (Δ ${(meas.position - t.center).toFixed(2)})` : ''),
        )
      }
      traces.push({
        type: 'scatter',
        mode: 'markers',
        x: xs,
        y: ys,
        text,
        hovertemplate: '%{text}<extra></extra>',
        legendgroup: row.id,
        showlegend: false,
        marker: {
          symbol: 'triangle-up',
          size: 10,
          color: seriesColor(state.slots[row.id], dark.value),
          line: { color: dark.value ? '#1a1a19' : '#fcfcfb', width: 2 },
        },
        xaxis: 'x',
        yaxis: stacked && onOutput ? 'y2' : 'y',
      })
    }
  }

  const shapes: unknown[] = []
  const annotations: unknown[] = []
  if (state.showBandWindows) {
    for (const b of bandDefinitions.value) {
      shapes.push({
        type: 'rect', xref: 'x', yref: 'paper', x0: b.lo, x1: b.hi, y0: 0, y1: 1,
        fillcolor: dark.value ? 'rgba(57,135,229,0.10)' : 'rgba(42,120,214,0.07)', line: { width: 0 }, layer: 'below',
      })
      annotations.push({
        x: (b.lo + b.hi) / 2, xref: 'x', y: 1, yref: 'paper', yanchor: 'top', text: b.name,
        showarrow: false, textangle: -90, font: { size: 9, color: muted },
      })
    }
  }

  const axis = { gridcolor: grid, zeroline: false, linecolor: grid, tickcolor: grid, color: muted }
  const yTitle = (q: string) => Y_TITLE[q] ?? 'Value (mixed quantities)'
  const layout: Record<string, unknown> = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: ink, size: 12, family: 'Roboto, system-ui, sans-serif' },
    margin: { l: 64, r: 16, t: 8, b: 48 },
    hovermode: ids.length <= 6 ? 'x unified' : 'closest',
    hoverlabel: { bgcolor: dark.value ? '#262625' : '#ffffff', font: { color: ink } },
    legend: { orientation: 'h', y: 1.02, yanchor: 'bottom', x: 0, font: { color: muted } },
    uirevision: 'keep',
    shapes,
    annotations,
    xaxis: { ...axis, title: { text: 'Wavelength (nm)' }, anchor: stacked ? 'y2' : 'y' },
    yaxis: {
      ...axis,
      title: { text: yTitle(m === 'processed' ? qOut : qIn) },
      domain: stacked ? [0.53, 1] : [0, 1],
    },
  }
  if (stacked) {
    layout.yaxis2 = { ...axis, title: { text: yTitle(qOut) }, domain: [0, 0.47] }
    layout.margin = { l: 64, r: 16, t: 28, b: 48 }
  }
  return { traces, layout }
})

async function render() {
  if (!el.value) return
  const { traces, layout } = figure.value
  await Plotly.react(el.value, traces, layout, {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ['lasso2d', 'select2d'],
    toImageButtonOptions: { format: 'png', filename: 'swirl_spectra', scale: 2 },
  })
}

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
  <div class="position-relative h-100">
    <div ref="el" class="h-100 w-100" />
    <div v-if="!visibleIds.length" class="position-absolute d-flex align-center justify-center text-muted" style="inset: 0; pointer-events: none">
      Tick spectra in the left panel to plot them.
    </div>
  </div>
</template>
