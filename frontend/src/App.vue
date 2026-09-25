<script setup lang="ts">
import {
  mdiChevronDown,
  mdiChevronUp,
  mdiContentSaveOutline,
  mdiFileOutline,
  mdiFolderOpenOutline,
  mdiWeatherNight,
  mdiWhiteBalanceSunny,
} from '@mdi/js'
import { computed, onMounted, ref } from 'vue'
import { useTheme } from 'vuetify'

import BandsPanel from './components/BandsPanel.vue'
import DetailsPanel from './components/DetailsPanel.vue'
import DrillholeView from './components/DrillholeView.vue'
import QcPanel from './components/QcPanel.vue'
import RecipePanel from './components/RecipePanel.vue'
import SpectrumPlot from './components/SpectrumPlot.vue'
import WorkspacePanel from './components/WorkspacePanel.vue'
import { init, newProject, openProject, recipeRemovesContinuum, saveProject, state, visibleIds } from './store'

const theme = useTheme()
const dark = computed(() => theme.current.value.dark)
const tab = ref('qc')
const bottomOpen = ref(true)
const projectInput = ref<HTMLInputElement | null>(null)

async function onProjectFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) await openProject(file)
  input.value = ''
}

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
      <v-app-bar-title style="flex: none">
        <span class="font-weight-bold">SWIRL</span>
        <span class="text-caption text-muted ml-2">{{ state.version }}</span>
      </v-app-bar-title>
      <div class="d-flex align-center ga-1 ml-6">
        <v-btn :icon="mdiFileOutline" size="small" title="New project" @click="newProject" />
        <v-btn :icon="mdiFolderOpenOutline" size="small" title="Open a project (.swirl)" @click="projectInput?.click()" />
        <v-btn :icon="mdiContentSaveOutline" size="small" title="Save the project (.swirl)" :disabled="!state.spectra.length" @click="saveProject" />
        <input ref="projectInput" type="file" accept=".swirl" hidden @change="onProjectFile" />
        <v-text-field
          v-model="state.project.name"
          placeholder="Untitled project"
          density="compact"
          variant="plain"
          hide-details
          class="ml-2"
          style="width: 220px"
        />
        <span v-if="state.project.dirty && state.spectra.length" class="text-caption text-warning" title="Unsaved changes">● unsaved</span>
      </div>
      <v-spacer />
      <v-btn :icon="dark ? mdiWhiteBalanceSunny : mdiWeatherNight" title="Light / dark" @click="toggleTheme" />
    </v-app-bar>

    <v-navigation-drawer permanent width="310" border="e">
      <WorkspacePanel />
    </v-navigation-drawer>

    <v-navigation-drawer permanent location="right" width="360" border="s">
      <RecipePanel />
    </v-navigation-drawer>

    <v-main class="d-flex flex-column" style="height: 100vh">
      <div class="d-flex align-center ga-3 px-3 py-1 border-b flex-wrap">
        <v-btn-toggle v-model="state.mainView" mandatory density="compact" variant="tonal" color="primary" divided>
          <v-btn value="spectra" size="small">Spectra</v-btn>
          <v-btn value="drillhole" size="small">Drill hole</v-btn>
        </v-btn-toggle>
        <v-btn-toggle
          v-if="state.mainView === 'spectra'"
          v-model="state.viewMode"
          mandatory
          density="compact"
          variant="outlined"
          divided
          :disabled="!hasProcessed"
        >
          <v-btn value="input" size="small">Input</v-btn>
          <v-btn value="processed" size="small">Processed</v-btn>
          <v-btn value="both" size="small">Both</v-btn>
        </v-btn-toggle>
        <v-divider vertical class="my-1" />
        <v-switch
          v-model="state.continuum.on"
          :disabled="recipeRemovesContinuum"
          label="Continuum removed"
          class="flex-grow-0"
          :title="recipeRemovesContinuum ? 'The recipe already removes the continuum' : 'Divide by the upper convex hull, after the recipe'"
        />
        <v-text-field
          v-model="state.continuum.start"
          label="from" placeholder="auto"
          suffix="nm"
          density="compact"
          style="max-width: 120px"
          class="mono"
          inputmode="decimal"
          persistent-placeholder
          :disabled="!state.continuum.on || recipeRemovesContinuum"
          :error="!!state.continuumError"
        />
        <v-text-field
          v-model="state.continuum.stop"
          label="to" placeholder="auto"
          suffix="nm"
          density="compact"
          style="max-width: 120px"
          class="mono"
          inputmode="decimal"
          persistent-placeholder
          :disabled="!state.continuum.on || recipeRemovesContinuum"
          :error="!!state.continuumError"
        />
        <span class="text-caption" :class="state.continuumError ? 'text-error' : 'text-muted'">
          {{ state.continuumError || (recipeRemovesContinuum ? 'continuum removed in the recipe' : '') }}
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
