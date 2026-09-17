/**
 * 轻量 Markdown 渲染（08 §5：对话流需支持 Markdown 渲染、代码高亮、复制）。
 *
 * **为什么自己写**：引入 marked + highlight.js 会让前端包体翻数倍，
 * 而本项目只需要一个很小子集（标题/列表/代码块/行内代码/粗斜体/链接）。
 *
 * ⚠️ **安全**：AI 的输出是**不可信内容**（可能被提示注入诱导产出 HTML）。
 * 因此先把所有 HTML 转义，再对**我们自己生成的**标签做替换 ——
 * 顺序不能反，否则就是 XSS 漏洞。这也是不引 marked 的原因之一：
 * 自己写的转义链路更短、更容易审。
 */

/** HTML 转义（必须最先执行）。 */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 行内元素（在已转义的文本上操作）。 */
function renderInline(text: string): string {
  return (
    text
      // 行内代码
      .replace(/`([^`]+)`/g, '<code class="md-code">$1</code>')
      // 粗体
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      // 斜体（避免匹配到已处理的粗体残留）
      .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
      // 链接：只允许 http/https，防 javascript: 协议
      .replace(
        /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
      )
  )
}

/**
 * 渲染 Markdown 片段为 HTML。
 *
 * 支持：围栏代码块、标题（#~####）、无序/有序列表、引用、水平线、
 * 行内代码、粗体、斜体、链接、段落。
 */
export function renderMarkdown(source: string): string {
  if (!source) return ''

  const lines = source.split('\n')
  const out: string[] = []
  let inCode = false
  let codeBuffer: string[] = []
  let codeLang = ''
  let listType: 'ul' | 'ol' | null = null

  const closeList = (): void => {
    if (listType) {
      out.push(`</${listType}>`)
      listType = null
    }
  }

  for (const raw of lines) {
    // ---- 围栏代码块 ----
    const fence = raw.match(/^```(.*)$/)
    if (fence) {
      if (inCode) {
        const code = escapeHtml(codeBuffer.join('\n'))
        const langAttr = codeLang ? ` data-lang="${escapeHtml(codeLang)}"` : ''
        out.push(`<pre class="md-pre"${langAttr}><code>${code}</code></pre>`)
        codeBuffer = []
        codeLang = ''
        inCode = false
      } else {
        closeList()
        inCode = true
        codeLang = fence[1].trim()
      }
      continue
    }
    if (inCode) {
      codeBuffer.push(raw)
      continue
    }

    // ---- 空行 ----
    if (!raw.trim()) {
      closeList()
      continue
    }

    const escaped = escapeHtml(raw)

    // ---- 标题 ----
    const heading = escaped.match(/^(#{1,4})\s+(.*)$/)
    if (heading) {
      closeList()
      const level = heading[1].length
      out.push(`<h${level} class="md-h">${renderInline(heading[2])}</h${level}>`)
      continue
    }

    // ---- 水平线 ----
    if (/^(-{3,}|\*{3,})$/.test(escaped.trim())) {
      closeList()
      out.push('<hr class="md-hr" />')
      continue
    }

    // ---- 引用 ----
    const quote = escaped.match(/^&gt;\s?(.*)$/)
    if (quote) {
      closeList()
      out.push(`<blockquote class="md-quote">${renderInline(quote[1])}</blockquote>`)
      continue
    }

    // ---- 无序列表 ----
    const ul = escaped.match(/^\s*[-*+]\s+(.*)$/)
    if (ul) {
      if (listType !== 'ul') {
        closeList()
        out.push('<ul class="md-ul">')
        listType = 'ul'
      }
      out.push(`<li>${renderInline(ul[1])}</li>`)
      continue
    }

    // ---- 有序列表 ----
    const ol = escaped.match(/^\s*\d+\.\s+(.*)$/)
    if (ol) {
      if (listType !== 'ol') {
        closeList()
        out.push('<ol class="md-ol">')
        listType = 'ol'
      }
      out.push(`<li>${renderInline(ol[1])}</li>`)
      continue
    }

    // ---- 普通段落 ----
    closeList()
    out.push(`<p class="md-p">${renderInline(escaped)}</p>`)
  }

  // 未闭合的代码块（流式过程中很常见）—— 按已收到的内容渲染，避免整段消失
  if (inCode && codeBuffer.length) {
    out.push(
      `<pre class="md-pre"><code>${escapeHtml(codeBuffer.join('\n'))}</code></pre>`,
    )
  }
  closeList()

  return out.join('')
}
