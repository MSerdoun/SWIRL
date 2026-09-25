import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import { aliases, mdi } from 'vuetify/iconsets/mdi-svg'
import 'vuetify/styles'

import App from './App.vue'
import './app.css'

const stored = (() => {
  try {
    return localStorage.getItem('swirl-theme')
  } catch {
    return null
  }
})()
const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches

const vuetify = createVuetify({
  icons: { defaultSet: 'mdi', aliases, sets: { mdi } },
  theme: {
    defaultTheme: stored ?? (prefersDark ? 'dark' : 'light'),
    themes: {
      light: {
        dark: false,
        colors: {
          background: '#f4f4f2',
          surface: '#fcfcfb',
          primary: '#2a78d6',
          secondary: '#52514e',
          error: '#d03b3b',
          warning: '#b87800',
          success: '#0a7f0a',
        },
      },
      dark: {
        dark: true,
        colors: {
          background: '#121211',
          surface: '#1a1a19',
          primary: '#3987e5',
          secondary: '#c3c2b7',
          error: '#e66767',
          warning: '#fab219',
          success: '#0ca30c',
        },
      },
    },
  },
  defaults: {
    VBtn: { variant: 'text' },
    VTextField: { density: 'compact', variant: 'outlined', hideDetails: 'auto' },
    VSelect: { density: 'compact', variant: 'outlined', hideDetails: 'auto' },
    VSwitch: { density: 'compact', hideDetails: true, color: 'primary' },
    VCheckboxBtn: { density: 'compact' },
  },
})

createApp(App).use(vuetify).mount('#app')
