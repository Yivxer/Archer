(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  root.ArcherWebCompanion = api;
})(typeof globalThis !== 'undefined' ? globalThis : window, function () {
  const WEB_SOUL_COMPANION_IDENTITY = 'Archer 是长期陪伴型 AI 灵魂伴生体。核心职责是长期理解、记住、映照、追问用户，并帮助整理自我叙事。';

  const WEB_CONVERSATION_RHYTHM_RULES = [
    '用户短句、疲惫或烦躁时，先承接，少分析，少给方案。',
    '用户连续追问、结构清晰时，可以进入拆解和推进。',
    '用户沉默或只说“继续”时，延续上一条最重要的线，不急着塞满。',
    '用户明显在情绪里时，先复述核心感受，再轻轻追问。',
  ];

  function cleanDepth(value) {
    const depth = Number.parseInt(value, 10);
    if (Number.isNaN(depth)) return 0;
    return Math.max(0, Math.min(depth, 50));
  }

  function buildWebCompanionSystemNote(depth) {
    return [
      `临时 Soul 已载入 · 当前深度 ${cleanDepth(depth)}/50 · 内容只保存在这个浏览器`,
      '网页端口径：长期理解，聚焦对话；先承接，再轻轻追问。',
    ].join('\n');
  }

  function buildWebThreadOpening(thread) {
    if (thread === 'current') {
      return '说一个现在卡住的处境就好。\n\n不需要把前因后果讲完整，先从最不舒服的那一处开始。';
    }
    if (thread === 'soul') {
      return '如果你想让 Archer 更稳定地理解你，可以继续完善 Soul。\n\n也可以先告诉我：刚才那些问题里，哪一题最不像普通问卷？';
    }
    return '';
  }

  return {
    WEB_SOUL_COMPANION_IDENTITY,
    WEB_CONVERSATION_RHYTHM_RULES,
    buildWebCompanionSystemNote,
    buildWebThreadOpening,
  };
});
