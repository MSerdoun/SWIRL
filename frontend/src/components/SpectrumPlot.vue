<script setup lang="ts">
import Plotly from 'plotly.js-dist-min'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useTheme } from 'vuetify'

import { seriesColor } from '../palette'
import { state, visibleIds } from '../store'

const Y_TITLE: Record<string, string> = {
  reflectance: 'Reflectance',
  continuum_removed: 'Hull quotient',
  raw: 'Raw DN',
}

const el = ref<HTMLDivElement | null>(null)
const theme = useTheme()
const dark = computed(() => theme.current.value.dark)
let observer: ResizeObserver | undefined

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
