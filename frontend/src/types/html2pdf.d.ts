declare module 'html2pdf.js' {
  interface Html2PdfOptions {
    margin?: number | number[]
    filename?: string
    image?: { type?: string; quality?: number }
    html2canvas?: Record<string, any>
    jsPDF?: Record<string, any>
    pagebreak?: Record<string, any>
    enableLinks?: boolean
    [key: string]: any
  }

  interface Html2PdfInstance {
    set(options: Html2PdfOptions): Html2PdfInstance
    from(element: HTMLElement | string): Html2PdfInstance
    save(): Promise<void>
    toPdf(): Html2PdfInstance
    get(type: string): Promise<any>
    output(type: string, options?: any): Promise<any>
  }

  function html2pdf(): Html2PdfInstance
  function html2pdf(element: HTMLElement, options?: Html2PdfOptions): Html2PdfInstance
  export default html2pdf
}
