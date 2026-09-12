/**
 * 极简日志：内存环形缓冲（交付代码禁止 console.* 残留，AGENTS.md §5）。
 * 排障时可调用 dump() 取最近记录。
 */

const BUFFER_SIZE = 200

export type LogLevel = 'info' | 'warn' | 'error'

export interface LogEntry {
  ts: string
  level: LogLevel
  tag: string
  message: string
}

const entries: LogEntry[] = []

function log(level: LogLevel, tag: string, message: string): void {
  entries.push({
    ts: new Date().toISOString(),
    level,
    tag,
    message,
  })
  if (entries.length > BUFFER_SIZE) {
    entries.splice(0, entries.length - BUFFER_SIZE)
  }
}

export const logger = {
  info: (tag: string, message: string) => log('info', tag, message),
  warn: (tag: string, message: string) => log('warn', tag, message),
  error: (tag: string, message: string) => log('error', tag, message),
  dump: (): readonly LogEntry[] => entries.slice(),
}
