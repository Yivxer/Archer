import { describe, expect, it } from 'vitest'

import { extractMarkdownPathRefs } from './fileRefHelpers'

describe('extractMarkdownPathRefs', () => {
  it('keeps an explicit article path even when the message mentions publishing', () => {
    const text = '昨天发布的文章/Users/Yivxer/Documents/第二大脑的下一步.md，反响不好，帮我分析'

    expect(extractMarkdownPathRefs(text)).toEqual([expect.objectContaining({
      path: '/Users/Yivxer/Documents/第二大脑的下一步.md',
      attachStatus: 'reading',
    })])
  })
})
