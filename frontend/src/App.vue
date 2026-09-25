<script setup lang="ts">
import { mdiChevronDown, mdiChevronUp, mdiWeatherNight, mdiWhiteBalanceSunny } from '@mdi/js'
import { computed, onMounted, ref } from 'vue'
import { useTheme } from 'vuetify'

import BandsPanel from './components/BandsPanel.vue'
import DetailsPanel from './components/DetailsPanel.vue'
import DrillholeView from './components/DrillholeView.vue'
import QcPanel from './components/QcPanel.vue'
import RecipePanel from './components/RecipePanel.vue'
import SpectrumPlot from './components/SpectrumPlot.vue'
import WorkspacePanel from './components/WorkspacePanel.vue'
import { init, state, visibleIds } from './store'

const theme = useTheme()
const dark = computed(() => theme.current.value.dark)
const tab = ref('qc')
const bottomOpen = ref(true)

function toggleTheme() {
  const next = dark.value ? 'light' : 'dark'
  theme.change(next)
  try {
    localStorage.setItem('swirl-theme', next)
  } catch {
    /* private mode: the choice just isn't remembered */
  }
}

const hasProcessed = computed(() => visibleIds.value.some((id) => state.processed[id]))

onMounted(init)
</script>

<template>
  <v-app>
    <v-app-bar density="compact" flat border="b">
      <v-app-bar-title>
        <span class="font-weight-bold">SWIRL</span>
        <span class="text-caption text-muted ml-2">VNIR-SWIR spectra · {{ state.version }}</span>
      </v-app-bar-title>
      <v-btn :icon="dark ? mdiWhiteBalanceSunny : mdiWeatherNight" title="Light / dark" @click="toggleTheme" />
    </v-app-bar>

    <v-navigation-drawer permanent width="310" border="e">
      <WorkspacePanel />
    </v-navigation-drawer>

    <v-navigation-drawer permanent location="right" width="360" border="s">
      <RecipePanel />
    </v-navigation-drawer>

    <v-main class="d-flex flex-column" style="height: 100vh">
      <div class="d-flex align-center px-3 py-1 border-b">
        <v-btn-toggle v-model="state.mainView" mandatory density="compact" variant="tonal" color="primary" divided class="mr-4">
          <v-btn value="spectra" size="small">Spectra</v-btn>
          <v-btn value="drillhole" size="small">Drill hole</v-btn>
        </v-btn-toggle>
        <template v-if="state.mainView === 'spectra'">
        <v-btn-toggle v-model="state.viewMode" mandatory density="compact" variant="outlined" divided :disabled="!hasProcessed">
          <v-btn value="input" size="small">Input</v-btn>
          <v-btn value="processed" size="small">Processed</v-btn>
          <v-btn value="both" size="small">Both</v-btn>
        </v-btn-toggle>
        <span class="text-caption text-muted ml-3">
          {{ hasProcessed ? 'Recipe applied to the shown spectra' : 'No active recipe step — showing input' }}
        </span>
        </template>
        <span v-else class="text-caption text-muted">
          The log shows the recipe output, the band parameters and QC of every sample of the hole.
        </span>
      </div>
      <div class="flex-grow-1" style="min-height: 0">
        <SpectrumPlot v-if="state.mainView === 'spectra'" />
        <DrillholeView v-else />
      </div>
      <div class="border-t d-flex flex-column" :style="{ height: bottomOpen ? '340px' : '40px', flex: 'none' }">
        <div class="d-flex align-center">
          <v-tabs v-model="tab" density="compact" color="primary" @update:model-value="bottomOpen = true">
            <v-tab value="qc">Quality control</v-tab>
            <v-tab value="bands">Band parameters</v-tab>
            <v-tab value="details">Details &amp; history</v-tab>
          </v-tabs>
          <v-spacer />
          <v-btn :icon="bottomOpen ? mdiChevronDown : mdiChevronUp" size="small" @click="bottomOpen = !bottomOpen" />
        </div>
        <div v-show="bottomOpen" class="flex-grow-1" style="min-height: 0">
          <QcPanel v-if="tab === 'qc'" />
          <BandsPanel v-else-if="tab === 'bands'" />
          <DetailsPanel v-else />
        </div>
      </div>
    </v-main>

    <v-snackbar v-model="state.notice.show" :color="state.notice.color" timeout="5000" location="bottom left">
      <span style="white-space: pre-line">{{ state.notice.text }}</span>
    </v-snackbar>
  </v-app>
</template>
