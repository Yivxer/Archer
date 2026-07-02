function pickVariant(options: string[], seed: string): string {
  if (!options.length) return ''
  let hash = 0
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash + seed.charCodeAt(index) * (index + 1)) % options.length
  }
  return options[hash] ?? options[0]
}

function wantsHugoPublish(text: string): boolean {
  const lowered = text.toLowerCase()
  const publishSignal = /部署|上线|发布|枫弋|札记|博客|iver\.yivxer|yivxer-blog/.test(lowered)
  const localMarkdownArticle = /\/users\/.+\.md/.test(lowered) && /文章|笔记/.test(lowered)
  return publishSignal || localMarkdownArticle
}

/** 等待模型首 token 前的短暂承接语；不写入最终回复或会话存档。 */
export function buildThinkingMutter(text: string, fileCount = 0): string {
  const trimmed = text.trim()
  const lowered = trimmed.toLowerCase()
  const seed = trimmed.slice(0, 64) || '…'

  if (wantsHugoPublish(trimmed)) {
    return pickVariant([
      '发布链路…先确认稿子和分类。',
      '嗯，得先摸清要发哪篇。',
      '枫弋札记那边，我翻翻材料。',
    ], seed)
  }

  if (/修复|报错|bug|改代码|实现|重构|构建|测试|build|test|debug/.test(lowered)) {
    return pickVariant([
      '嗯，先看看哪里出了问题。',
      '好，顺着报错摸一下。',
      '得找找影响范围。',
    ], seed)
  }

  if (/obsidian|写入|保存|整理成文档|笔记/.test(lowered)) {
    return pickVariant([
      '笔记的事…先别动原意。',
      '嗯，整理一下再动笔。',
      '这个得想清楚写不写进库里。',
    ], seed)
  }

  if (fileCount > 0 || /\/users\/|\.md|\.ts|\.tsx|\.py|\.json/.test(lowered)) {
    return pickVariant([
      '有材料，我先翻一眼。',
      '嗯…看看文件里说了什么。',
      '先读读你给的这份。',
    ], seed)
  }

  if (/难过|焦虑|委屈|害怕|累|烦|崩溃|孤独|心情|感觉|难受|不开心/.test(trimmed)) {
    return pickVariant([
      '嗯，我听到了。',
      '……先缓缓。',
      '这件事，我陪你想一想。',
    ], seed)
  }

  if (/为什么|怎么理解|是什么|如何|怎么办|你觉得|知道|模型|能否|能不能|吗？|吗\?/.test(trimmed)) {
    return pickVariant([
      '嗯…让我想想怎么讲。',
      '这个问题，得从哪儿说起呢。',
      '有意思，先捋一下。',
      '唔，怎么回答比较好…',
      '让我琢磨琢磨。',
    ], seed)
  }

  return pickVariant([
    '嗯…',
    '让我想想。',
    '稍等，我理一下。',
    '唔…',
    '好，我看一眼。',
  ], seed)
}
