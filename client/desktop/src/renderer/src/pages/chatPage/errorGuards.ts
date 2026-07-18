import { ChatBusyError, StreamIdleTimeoutError } from '../../adapters/localArcher'

export function isAbortError(error: unknown): boolean {
  return (error instanceof DOMException && error.name === 'AbortError') || (error instanceof Error && error.name === 'AbortError')
}

export function isRequestTimeout(error: unknown): boolean {
  return error instanceof StreamIdleTimeoutError
    || (error instanceof Error && /timed out|timeout|超时/i.test(error.message))
}

export function isChatBusy(error: unknown): boolean {
  return error instanceof ChatBusyError
    || (error instanceof Error && /chat_busy|上一轮对话仍在处理中|仍在处理/i.test(error.message))
}
