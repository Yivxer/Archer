import type { ArcherAdapter } from '../types'

export const mockArcher: ArcherAdapter = {
  status: {
    adapter: 'mock',
    model: 'deepseek-chat',
    mode: 'operator',
    memoryCount: 128,
    skillCount: 18,
    tokenUsage: {
      sessionTotal: 12800,
      sessionPrompt: 9200,
      sessionCompletion: 3600,
      callCount: 3,
      lastCallTotal: 2400,
      lastCallPrompt: 1800,
      lastCallCompletion: 600,
      limit: 1000000,
      percentUsed: 0.0128
    }
  },
  chat: {
    initialMessages: [],
    toolProgress: [
      { name: 'skill_router', state: 'ready', active: true },
      { name: 'memory.retrieve', state: 'mock' },
      { name: 'local SSE', state: 'next' }
    ],
    toolEvents: [
      {
        id: 'mock-memory',
        name: 'memory.retrieve',
        status: 'complete',
        risk: 'low',
        summary: '读取与桌面端计划相关的长期记忆',
        detail: 'scope: Archer Desktop, limit: 8'
      },
      {
        id: 'mock-file',
        name: 'obsidian_write',
        status: 'waiting',
        risk: 'medium',
        summary: '把本轮客户端进度写入 Archer 客户端日志',
        detail: 'target: Archer客户端.md',
        draft: {
          path: 'Archer客户端.md',
          contentPreview: '记录桌面端 Markdown 渲染、工具卡片和错误恢复优化。'
        },
        requiresApproval: true
      },
      {
        id: 'mock-shell',
        name: 'shell.execute',
        status: 'blocked',
        risk: 'high',
        summary: '运行可能修改本地文件的命令前必须确认',
        detail: 'policy: require explicit approval',
        draft: {
          command: 'npm run build'
        },
        requiresApproval: true
      }
    ],
    mockReply: [
      '已收到。这一版还在 **预览模式** 中，真实回复会在本地 SSE 接入后替换。',
      '',
      '- Markdown 列表会正常渲染',
      '- 链接和 `inline code` 会变得可读',
      '- 代码块会带复制按钮',
      '',
      '```bash',
      'npm run build',
      '```'
    ].join('\n')
  },
  sessions: [
    { id: 's1', title: '桌面端产品范围确认', date: '今天', turns: 18, tone: 'operator' },
    { id: 's2', title: 'Soul 深度问答输入体验', date: '昨天', turns: 31, tone: 'critic' },
    { id: 's3', title: '记忆质量与 pending 审阅', date: '本周', turns: 14, tone: 'coach' },
    { id: 's4', title: 'Archer v1.2 稳定在场版', date: '本周', turns: 27, tone: 'mirror' }
  ],
  memory: [
    {
      id: 101,
      status: 'confirmed',
      type: 'decision',
      content: 'Archer Desktop 第一版先做 macOS 静态工作台原型，不接真实后端。',
      confidence: '0.92',
      source: 'mock',
      depth: 3
    },
    {
      id: 102,
      status: 'confirmed',
      type: 'preference',
      content: '界面气质偏安静工作台，继承圆环与五色谱系，但不做营销页。',
      confidence: '0.88',
      source: 'mock',
      depth: 4
    },
    {
      id: 103,
      status: 'pending',
      type: 'todo',
      content: '第二阶段优先为 Archer 增加本地 HTTP API 与 SSE 流式输出。',
      confidence: '0.81',
      source: 'mock',
      depth: 2
    },
    {
      id: 104,
      status: 'pending',
      type: 'risk',
      content: '不要让 renderer 直接接触 API key 或任意本地文件路径。',
      confidence: '0.86',
      source: 'mock',
      depth: 5
    }
  ],
  skills: [
    { name: 'obsidian_search', description: '搜索 Obsidian vault 笔记', risk: 'low', enabled: true },
    { name: 'file_ops', description: '读取和写入本地文件，需要明确路径边界', risk: 'medium', enabled: true },
    { name: 'shell', description: '执行终端命令，沿用 Archer policy 分级确认', risk: 'high', enabled: true },
    { name: 'pdf_reader', description: '提取 PDF 正文内容', risk: 'low', enabled: true },
    { name: 'github_ops', description: 'GitHub 仓库操作，默认需要确认', risk: 'high', enabled: false },
    { name: 'web_fetch', description: '抓取网页正文并整理结果', risk: 'low', enabled: true }
  ],
  modes: {
    current: 'listener',
    default: 'listener',
    modes: [
      { id: 'listener', label: '倾听者', source: 'file', active: true },
      { id: 'questioner', label: '追问者', source: 'file', active: false },
      { id: 'philosopher', label: '哲学家', source: 'file', active: false },
      { id: 'writer', label: '作家', source: 'file', active: false },
      { id: 'witness', label: '见证者', source: 'file', active: false },
    ]
  },
  proactive: {
    enabled: true,
    items: [
      {
        id: 'mock-deep-memory',
        kind: 'deep_memory_review',
        severity: 'medium',
        title: '有一条深层记忆需要回看',
        detail: '预览模式示例：连接本地 API 后会读取真实触达建议。',
        action: '打开记忆',
        target: 'Memory'
      }
    ]
  },
  soulProfile: {
    empty: false,
    sections: [
      { id: 'current_life_stage', label: '当前阶段', items: ['Archer 进入灵魂伴生体阶段'] },
      { id: 'core_values', label: '核心价值', items: ['自己能做的事情尽量自己做好'] },
      { id: 'emotional_patterns', label: '情绪模式', items: ['焦虑时会用规划填充行动前的不确定'] },
      { id: 'life_themes', label: '人生主题', items: ['从失去旧记忆到重建新系统'] },
      { id: 'creative_identity', label: '创作身份', items: ['把说不清的东西写清楚'] },
      { id: 'growth_markers', label: '成长标记', items: ['开始把阶段变化记录为可回看的轨迹'] },
    ]
  },
  soulFiles: {
    'SOUL.md':
      '# SOUL.md\n\n这部分用于描述用户是谁、价值观、工作方式，以及 Archer 应该如何理解长期主题。\n\n当前原型只读展示，后续通过本地 API 读取真实文件。',
    'MEMORY.md':
      '# MEMORY.md\n\n当前项目：Archer Desktop 静态原型。\n\n开放问题：何时接入本地 API、如何呈现工具确认、如何处理记忆审阅。',
    'COVENANT.md':
      '# COVENANT.md\n\n根契约不可由客户端静默修改。任何边界变化都必须显式确认，并保留审阅痕迹。',
    'PRESENCE.md':
      '# PRESENCE.md\n\n回应应保持清晰、克制、可执行。桌面端应该帮助用户看见结构，而不是制造噪音。'
  },
  periodReviews: {
    weekly: {
      period: 'weekly',
      title: '周复盘',
      window: { days: 7, start: '2026-05-18T00:00:00', end: '2026-05-25T00:00:00' },
      metrics: { sessions: 4, user_turns: 27, memories: 8, deep_memories: 5 },
      themes: [{ type: 'project_mythology', count: 3 }, { type: 'growth_marker', count: 2 }],
      highlights: ['Archer 开始从工具台转向灵魂伴生体工作台。'],
      growth_markers: ['开始把阶段变化记录为可回看的轨迹。'],
      suggested_questions: ['下一期最小的推进动作是什么？'],
      markdown: '# 周复盘\n\n## 本期信号\n\n- Archer 开始从工具台转向灵魂伴生体工作台。\n\n## 成长标记\n\n- 开始把阶段变化记录为可回看的轨迹。\n'
    },
    monthly: {
      period: 'monthly',
      title: '月复盘',
      window: { days: 30, start: '2026-04-25T00:00:00', end: '2026-05-25T00:00:00' },
      metrics: { sessions: 12, user_turns: 93, memories: 21, deep_memories: 10 },
      themes: [{ type: 'life_theme', count: 5 }],
      highlights: ['本月主线集中在 Archer、博客和个人知识系统收束。'],
      growth_markers: ['更倾向先闭环，再扩张。'],
      suggested_questions: ['哪些变化已经从一次性进展，变成了稳定习惯？'],
      markdown: '# 月复盘\n\n## 本期信号\n\n- 本月主线集中在 Archer、博客和个人知识系统收束。\n'
    },
    life_stage: {
      period: 'life_stage',
      title: '人生阶段复盘',
      window: { days: 90, start: '2026-02-24T00:00:00', end: '2026-05-25T00:00:00' },
      metrics: { sessions: 31, user_turns: 240, memories: 52, deep_memories: 22 },
      themes: [{ type: 'self_narrative', count: 6 }],
      highlights: ['旧的零散工具使用，正在变成可维护的个人系统。'],
      growth_markers: ['开始用系统记录自己，而不是只靠意志记住自己。'],
      suggested_questions: ['这个阶段真正结束的旧叙事是什么？新的叙事又是什么？'],
      markdown: '# 人生阶段复盘\n\n## 本期信号\n\n- 旧的零散工具使用，正在变成可维护的个人系统。\n'
    }
  },
  journalReview: {
    configured: true,
    window: { days: 30, start: '2026-04-25T00:00:00', end: '2026-05-25T00:00:00' },
    metrics: { entries: 9, characters: 12400 },
    entries: [
      { path: '日记/2026-05-24.md', date: '2026-05-24', characters: 1300, preview: '今天把 Archer 的 Soul 页面往前推了一步，焦虑下降，专注变清楚。' }
    ],
    journal_emotions: { 焦虑: 3, 专注: 6, 疲惫: 2, 兴奋: 1, 平静: 4, 沮丧: 0 },
    session_emotions: { 焦虑: [], 专注: [], 疲惫: [], 兴奋: [], 平静: [], 沮丧: [] },
    markdown: '# Obsidian 日记回顾\n\n## 日记信号\n\n- 2026-05-24 · 2026-05-24.md：今天把 Archer 的 Soul 页面往前推了一步，焦虑下降，专注变清楚。\n\n## 情绪关键词\n\n- 焦虑 × 3\n- 专注 × 6\n'
  },
  settings: {
    provider: 'OpenAI-compatible',
    baseUrl: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
    apiKeyPreview: 'sk-••••••••••••••••',
    configPath: '~/.archer/archer.toml',
    memoryDbPath: '~/.archer/archer.db',
    sessionsPath: '~/.archer/sessions'
  }
}
