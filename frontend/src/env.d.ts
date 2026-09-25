/// <reference types="vite/client" />
declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}
declare module 'plotly.js-cartesian-dist-min' {
  const Plotly: {
    react: (el: HTMLElement, data: unknown[], layout: unknown, config?: unknown) => Promise<unknown>
    purge: (el: HTMLElement) => void
    Plots: { resize: (el: HTMLElement) => void }
  }
  export default Plotly
}
