(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  root.ArcherSoulProfile = api;
})(typeof globalThis !== 'undefined' ? globalThis : window, function () {
  const PROFILE_FIELDS = [
    'core_values',
    'recurring_fears',
    'creative_identity',
    'life_themes',
    'emotional_patterns',
    'relationship_patterns',
    'aesthetic_preferences',
    'project_mythology',
    'language_style',
    'important_questions',
    'current_life_stage',
  ];

  const INITIAL_FIELD_MAP = [
    ['core_values'],
    ['recurring_fears', 'life_themes'],
    ['recurring_fears'],
    ['creative_identity'],
    ['emotional_patterns'],
    ['core_values'],
    ['relationship_patterns'],
    ['language_style', 'creative_identity'],
    ['life_themes'],
    ['life_themes'],
  ];

  const DEEP_THEME_MAP = {
    emotion: ['emotional_patterns'],
    emotional: ['emotional_patterns'],
    fear: ['recurring_fears'],
    relation: ['relationship_patterns'],
    relationship: ['relationship_patterns'],
    project: ['project_mythology'],
    archer: ['project_mythology'],
    create: ['creative_identity'],
    creative: ['creative_identity'],
    aesthetic: ['aesthetic_preferences'],
    language: ['language_style'],
    question: ['important_questions'],
    self: ['life_themes'],
    life: ['life_themes'],
  };

  function normalizeSoulText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function emptyProfile() {
    return PROFILE_FIELDS.reduce((profile, field) => {
      profile[field] = [];
      return profile;
    }, {});
  }

  function appendUnique(profile, field, value, limit = 4) {
    const text = normalizeSoulText(value);
    if (!text || !profile[field] || profile[field].includes(text)) return;
    if (profile[field].length >= limit) return;
    profile[field].push(text);
  }

  function uniqueDeepAnswers(state = {}) {
    const answers = Array.isArray(state.deepAnswers) ? state.deepAnswers : [];
    const seen = new Set();
    return answers.filter((item, index) => {
      const id = item && normalizeSoulText(item.id || `${item.q || ''}:${index}`);
      if (!id || seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  }

  function soulDepth(state = {}) {
    const initialComplete = Boolean(state.initialComplete);
    return (initialComplete ? 10 : 0) + uniqueDeepAnswers(state).length;
  }

  function fieldsForDeepAnswer(item = {}) {
    const theme = normalizeSoulText(item.theme).toLowerCase();
    return DEEP_THEME_MAP[theme] || ['life_themes'];
  }

  function buildSoulProfileFromState(state = {}) {
    const profile = emptyProfile();
    const soulAnswers = state.soulAnswers || {};
    const initialAnswers = Array.isArray(state.initialAnswers) ? state.initialAnswers : [];

    appendUnique(profile, 'current_life_stage', soulAnswers[2]);
    appendUnique(profile, 'language_style', soulAnswers[3]);

    initialAnswers.forEach((item, index) => {
      const fields = INITIAL_FIELD_MAP[index] || ['life_themes'];
      fields.forEach((field) => appendUnique(profile, field, item && item.a));
      if (item && item.q) appendUnique(profile, 'important_questions', item.q, 6);
    });

    uniqueDeepAnswers(state).forEach((item) => {
      fieldsForDeepAnswer(item).forEach((field) => appendUnique(profile, field, item && item.a));
      if (item && item.q) appendUnique(profile, 'important_questions', item.q, 6);
    });

    return profile;
  }

  function buildSoulExport(state = {}, exportedAt = new Date().toISOString()) {
    return {
      version: 2,
      exportedAt,
      depth: soulDepth(state),
      soulAnswers: state.soulAnswers || {},
      initialAnswers: Array.isArray(state.initialAnswers) ? state.initialAnswers : [],
      deepAnswers: uniqueDeepAnswers(state),
      soulProfile: buildSoulProfileFromState(state),
    };
  }

  return {
    buildSoulExport,
    buildSoulProfileFromState,
    normalizeSoulText,
    soulDepth,
    uniqueDeepAnswers,
  };
});
