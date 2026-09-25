<script setup lang="ts">
// One row of the spectra list, kept deliberately light (plain HTML, no Vuetify components):
// with hundreds of spectra, only the rows whose own props change are re-rendered.
import { mdiDeleteOutline } from '@mdi/js'

import type { SpectrumSummary } from '../api'

defineProps<{
  s: SpectrumSummary
  visible: boolean
  color: string | null
  focused: boolean
}>()
const emit = defineEmits<{ toggle: [on: boolean]; focus: []; remove: [] }>()
</script>

<template>
  <div class="row" :class="{ focused }" @click="emit('focus')">
    <input
      type="checkbox"
      :checked="visible"
      :aria-label="`Show ${s.name}`"
      @click.stop
      @change="emit('toggle', ($event.target as HTMLInputElement).checked)"
    />
    <div class="text">
      <div class="name">
        <span v-if="color" class="swatch" :style="{ background: color }" />
        <span class="truncate">{{ s.name }}</span>
      </div>
      <div class="sub mono">
        <template v-if="s.hole_id">
          {{ s.hole_id }} · {{ s.depth_to != null && s.depth_to !== s.depth_from ? `${s.depth_from}–${s.depth_to}` : s.depth_from }} m
        </template>
        <template v-else>{{ s.quantity }} · {{ s.wl_min }}–{{ s.wl_max }} nm · {{ s.n_bands }} b</template>
      </div>
    </div>
    <button class="del" title="Remove" :aria-label="`Remove ${s.name}`" @click.stop="emit('remove')">
      <svg viewBox="0 0 24 24" width="16" height="16"><path :d="mdiDeleteOutline" fill="currentColor" /></svg>
    </button>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 52px;
  padding: 0 8px 0 14px;
  cursor: pointer;
  border-radius: 4px;
}
.row:hover {
  background: rgba(var(--v-theme-on-surface), 0.04);
}
.row.focused {
  background: rgba(var(--v-theme-primary), 0.12);
}
input[type='checkbox'] {
  width: 16px;
  height: 16px;
  accent-color: rgb(var(--v-theme-primary));
  cursor: pointer;
  flex: none;
}
.text {
  min-width: 0;
  flex: 1;
}
.name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.875rem;
}
.truncate {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sub {
  font-size: 11px;
  color: rgba(var(--v-theme-on-surface), 0.62);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.del {
  flex: none;
  border: 0;
  background: none;
  color: rgba(var(--v-theme-on-surface), 0.62);
  padding: 4px;
  border-radius: 50%;
  cursor: pointer;
  opacity: 0.6;
}
.row:hover .del {
  opacity: 1;
}
.del:hover {
  background: rgba(var(--v-theme-on-surface), 0.08);
}
</style>
