/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent
  export default component
}

declare module 'html2pdf.js/src/index.js' {
  import html2pdf from 'html2pdf.js'
  export default html2pdf
}
