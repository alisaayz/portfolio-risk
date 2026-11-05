'use strict';

const $ = id => document.getElementById(id);
const state = {context: null, positions: [], result: null, demo: true, metric: 'wealth', revision: 0, compare: false, alternativeInitialized: false};
let searchSequence = 0;
let searchTimer;
let searchMatches = [];
const percent = value => value === null || !Number.isFinite(value) ? 'Undefined' : `${(value * 100).toFixed(2)}%`;
const shortDate = value => new Date(`${value}T12:00:00`).toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'});
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
async function api(path, payload) {
  const response = await fetch(path, payload ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)} : {});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'The analysis could not complete.');
  return value;
}
function dirty() {
  clearReweightPreview();
  $('reweight-card').hidden = true;
  state.revision += 1;
  state.demo = false;
  $('input-label').textContent = 'Your entries · processed locally, without saving.';
  if (state.result) {
    $('results').classList.add('stale');
    $('result-context').textContent = 'Inputs changed. Run analysis to refresh these previous results.';
    $('download').disabled = true;
  }
}
function totals() {
  for (const key of ['a', 'b']) {
    const total = state.positions.reduce((sum, p) => sum + (Number.isFinite(p[key]) ? p[key] : 0), 0);
    $(`total-${key}`).textContent = `${total.toFixed(2)}%`;
    $(`total-${key}`).classList.toggle('invalid-total', Math.abs(total - 100) > 1e-8);
  }
}
function buttonLabel() {
  $('analyze').replaceChildren(document.createTextNode(state.compare ? 'Compare portfolios ' : 'Assess my portfolio '), element('span', '↗'));
}
function syncMode() {
  $('compare-mode').checked = state.compare;
  document.querySelectorAll('[data-comparison-only]').forEach(node => {
    node.hidden = !state.compare;
    node.querySelectorAll('input').forEach(input => {input.disabled = !state.compare;});
  });
  $('portfolio-names').classList.toggle('single', !state.compare);
  $('inputs-title').textContent = state.compare ? 'Your comparison' : 'Your portfolio';
  $('name-a-label').textContent = state.compare ? 'Current portfolio name' : 'Portfolio name';
  $('weight-a-heading').textContent = state.compare ? 'Current (%)' : 'Weight (%)';
  $('weight-help').textContent = state.compare ? 'Each portfolio column must total 100%. The alternative is a hypothetical scenario.' : 'Enter the share of your portfolio in each holding. The total must be 100%.';
  buttonLabel();
}
function copyCurrentWeights() {
  state.positions.forEach(position => {position.b = position.a;});
  state.alternativeInitialized = true;
}
function questionnaireFields() {
  $('risk-questions').replaceChildren();
  for (const question of state.context.risk_questionnaire.questions) {
    const label = element('label', question.prompt, 'risk-question');
    const select = document.createElement('select'); select.id = `preference-${question.id}`;
    const placeholder = element('option', 'Choose an answer or skip'); placeholder.value = ''; select.append(placeholder);
    for (const choice of question.choices) {const option = element('option', choice.label); option.value = choice.value; select.append(option);}
    select.addEventListener('change', dirty); label.append(select); $('risk-questions').append(label);
    if (question.help) $('risk-questions').append(element('p', question.help, 'field-help'));
  }
}
function renderPositions() {
  $('position-rows').replaceChildren();
  state.positions.forEach(position => {
    const row = element('tr');
    row.append(element('td', position.symbol));
    for (const key of ['a', 'b']) {
      const cell = element('td'), input = document.createElement('input');
      input.type = 'number'; input.min = '0'; input.max = '100'; input.step = 'any';
      input.value = String(position[key]);
      input.setAttribute('aria-label', `${position.symbol} weight in ${key === 'a' ? 'your portfolio' : 'the alternative'}, percent`);
      input.addEventListener('input', () => {position[key] = input.value === '' ? 0 : Number(input.value); totals(); dirty();});
      cell.append(input); row.append(cell);
      if (key === 'b') cell.dataset.comparisonOnly = '';
    }
    const cell = element('td'), remove = element('button', '×', 'remove-position');
    remove.type = 'button'; remove.setAttribute('aria-label', `Remove ${position.symbol}`);
    remove.addEventListener('click', () => {state.positions = state.positions.filter(p => p !== position); renderPositions(); dirty();});
    cell.append(remove); row.append(cell); $('position-rows').append(row);
  });
  totals();
  syncMode();
}
async function searchSymbols() {
  const sequence = ++searchSequence, query = $('add-symbol').value.trim();
  if (!query) {$('symbol-matches').replaceChildren(); searchMatches = []; return;}
  try {
    const value = await api(`/api/symbols?q=${encodeURIComponent(query)}`);
    if (sequence !== searchSequence) return;
    searchMatches = value.matches;
    $('symbol-matches').replaceChildren(...searchMatches.map(row => {
      const option = element('option'); option.value = row.symbol;
      option.label = `${row.security_name} · ${row.directory_type === 'ETF' ? 'ETF' : 'stock candidate'}`;
      return option;
    }));
  } catch (error) {$('load-status').textContent = error.message;}
}
async function addSymbol() {
  $('form-error').hidden = true;
  const symbol = $('add-symbol').value.trim().toUpperCase();
  if (!symbol) return;
  if (state.positions.some(p => p.symbol === symbol)) {$('load-status').textContent = `${symbol} is already in the table.`; return;}
  $('add-position').disabled = true;
  try {
    const known = state.context.instruments.find(i => i.symbol === symbol);
    if (!known) {
      const matches = await api(`/api/symbols?q=${encodeURIComponent(symbol)}`);
      const record = matches.matches.find(row => row.symbol === symbol);
      if (!record) throw new Error('Choose an exact ticker from the U.S. search results.');
      let job = await api('/api/instruments/load', {symbol});
      $('load-status').textContent = `Loading and auditing ${symbol} through the saved analysis cutoff…`;
      for (let attempt = 0; attempt < 90 && !['complete', 'failed'].includes(job.status); attempt++) {
        await new Promise(resolve => setTimeout(resolve, 800));
        job = await api(`/api/jobs/${job.job_id}`);
      }
      if (job.status === 'failed') throw new Error(`${symbol} could not be admitted: ${job.error}`);
      if (job.status !== 'complete') throw new Error(`${symbol} is still loading. Press Add later to check the same job; no duplicate download will be started.`);
      state.context.instruments.push({symbol, label: record.security_name});
      $('load-status').textContent = `${symbol}: structural checks passed. No independent price cross-check has been performed. ${job.warnings?.length || 0} review warning(s).`;
    } else {$('load-status').textContent = `${symbol} is available in the loaded data.`;}
    state.positions.push({symbol, a: 0, b: 0});
    $('add-symbol').value = ''; $('symbol-matches').replaceChildren();
    renderPositions(); dirty();
  } catch (error) {$('form-error').textContent = error.message; $('form-error').hidden = false; $('load-status').textContent = '';}
  finally {$('add-position').disabled = false;}
}
function loadDemo() {
  clearReweightPreview();
  $('reweight-card').hidden = true;
  state.revision += 1;
  $('load-status').textContent = '';
  $('add-symbol').value = '';
  const config = state.context.demo_configuration;
  $('name-a').value = config.portfolios[0].name;
  $('name-b').value = 'Alternative portfolio';
  $('as-of').value = config.as_of_date;
  $('risk-window').value = String(config.risk_window_sessions);
  $('vol-reference').value = '';
  state.positions = config.portfolios[0].positions.map(position => ({symbol: position.instrument_id, a: position.weight * 100, b: position.weight * 100}));
  state.compare = false; state.alternativeInitialized = false;
  $('risk-questions').querySelectorAll('select').forEach(select => {select.value = '';});
  state.demo = true; $('input-label').textContent = 'Demonstration holdings · edit to explore your own.';
  renderPositions();
}
function requestPayload(compare = state.compare) {
  const portfolios = (compare ? ['a', 'b'] : ['a']).map(key => {
    if (state.positions.some(p => !Number.isFinite(p[key]) || p[key] < 0)) throw new Error('Use finite, nonnegative allocation percentages.');
    const positions = state.positions.filter(p => p[key] > 0).map(p => ({instrument_id: p.symbol, weight: p[key] / 100}));
    const total = positions.reduce((sum, p) => sum + p.weight, 0);
    if (!positions.length || Math.abs(total - 1) > 1e-10) throw new Error(`${key === 'a' ? 'Your portfolio' : 'The alternative'} must total 100%. Weights are not automatically rescaled.`);
    return {id: `portfolio_${key}`, name: $(`name-${key}`).value.trim(), input_type: 'weights', positions};
  });
  const answers = {};
  for (const question of state.context.risk_questionnaire.questions) {
    const answer = $(`preference-${question.id}`).value;
    if (answer) answers[question.id] = answer;
  }
  return {configuration: {schema_version: 1, is_demo: state.demo, as_of_date: $('as-of').value,
    report_currency: 'USD', risk_window_sessions: Number($('risk-window').value),
    convention: 'fixed_weights_daily_rebalanced', portfolios},
    volatility_reference: $('vol-reference').value === '' ? null : Number($('vol-reference').value) / 100,
    risk_preferences: Object.keys(answers).length ? {questionnaire_id: state.context.risk_questionnaire.questionnaire_id, answers} : null};
}
function metricCards(value) {
  $('metrics').replaceChildren();
  $('metrics').classList.toggle('single', value.analysis.scenarios.length === 1);
  value.analysis.scenarios.forEach((portfolio, index) => {
    const card = element('article', undefined, `metric-card ${index ? 'b' : 'a'}`);
    card.append(element('p', portfolio.name, 'metric-name'), element('p', 'Annualized historical volatility', 'metric-label'),
      element('p', percent(portfolio.annualized_sample_volatility), 'metric-value'),
      element('p', `Maximum historical drawdown: ${percent(portfolio.maximum_drawdown)}`, 'metric-sub'));
    const comparison = value.reference_comparisons.find(row => row.portfolio_id === portfolio.id);
    if (comparison.volatility_reference !== null) card.append(element('span',
      `${comparison.comparison === 'above_reference' ? 'Above' : 'Within'} your ${percent(comparison.volatility_reference)} reference`,
      `reference-tag ${comparison.comparison === 'above_reference' ? 'above' : ''}`));
    $('metrics').append(card);
  });
}
function preferenceSummary(value) {
  const profile = value.risk_preferences;
  $('preference-card').hidden = !profile;
  if (!profile) return;
  const uncertain = Object.values(profile.answers).filter(answer => answer === 'unsure').length;
  $('preference-progress').textContent = `${profile.answered_questions} of 5 answered${uncertain ? `; ${uncertain} still uncertain` : ''}. Comfort with risk and ability to bear losses are kept separate.`;
  const output = $('preference-summary'); output.replaceChildren();
  for (const [title, statements] of [['Comfort with fluctuations', profile.willingness_statements], ['Access to money', profile.access_and_capacity_notes]]) {
    if (!statements.length) continue;
    output.append(element('h4', title)); const list = element('ul'); statements.forEach(text => list.append(element('li', text))); output.append(list);
  }
  profile.review_notes.forEach(text => output.append(element('p', text, 'notice source-notice')));
  for (const comparison of profile.historical_comparisons) {
    const portfolio = value.analysis.scenarios.find(row => row.id === comparison.portfolio_id);
    let text = `${portfolio.name}: the largest historical peak-to-trough decline was ${percent(comparison.historical_maximum_decline)}.`;
    if (comparison.stated_decline_comfort === null) text += ` A hypothetical $1,000 at that peak would have fallen to about $${comparison.illustrative_trough_balance.toFixed(0)}. No loss-comfort threshold has been inferred.`;
    else text += ` That is ${comparison.comparison === 'past_decline_above_stated_comfort' ? 'above' : 'at or below'} the ${percent(comparison.stated_decline_comfort)} decline you said would start feeling hard to tolerate.`;
    output.append(element('p', text));
  }
}
function drawChart() {
  if (!state.result) return;
  const values = state.result.chart_series, portfolios = state.result.analysis.scenarios;
  const width = 760, height = 270, left = 40, top = 15, right = 8, bottom = 12;
  const column = id => `${id}_${state.metric === 'wealth' ? 'wealth_index' : 'drawdown'}`;
  const all = portfolios.flatMap(p => values.map(row => row[column(p.id)]));
  let low = Math.min(...all), high = Math.max(...all);
  if (Math.abs(high - low) < 1e-12) {low -= .01; high += .01;}
  const pad = (high - low) * .06; low -= pad; high += pad;
  const x = index => left + index / Math.max(1, values.length - 1) * (width - left - right);
  const y = value => height - bottom - (value - low) / (high - low) * (height - top - bottom);
  const namespace = 'http://www.w3.org/2000/svg';
  const svgNode = (name, attributes) => {const node = document.createElementNS(namespace, name); for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value)); return node;};
  const svg = svgNode('svg', {viewBox: `0 0 ${width} ${height}`, 'aria-hidden': 'true'});
  for (let i = 0; i < 5; i++) {
    const value = low + i * (high - low) / 4;
    svg.append(svgNode('line', {x1: left, x2: width - right, y1: y(value), y2: y(value), class: 'grid'}));
    const text = svgNode('text', {x: left - 8, y: y(value) + 3, 'text-anchor': 'end', class: 'axis-label'});
    text.textContent = state.metric === 'wealth' ? value.toFixed(1) : `${(value * 100).toFixed(0)}%`; svg.append(text);
  }
  portfolios.forEach((portfolio, index) => {
    const path = values.map((row, i) => `${i ? 'L' : 'M'}${x(i).toFixed(2)},${y(row[column(portfolio.id)]).toFixed(2)}`).join(' ');
    svg.append(svgNode('path', {d: path, class: `series-${index ? 'b' : 'a'}`}));
  });
  $('chart').replaceChildren(svg);
  $('chart').setAttribute('aria-label', `${state.metric === 'wealth' ? 'Wealth index starting at one' : 'Drawdown from each running peak'} for ${portfolios.map(p => p.name).join(' and ')}, ${values[0].date} through ${values.at(-1).date}`);
  $('chart-start').textContent = shortDate(values[0].date); $('chart-end').textContent = shortDate(values.at(-1).date);
  $('chart-legend').replaceChildren(...portfolios.map((p, i) => element('span', p.name, i ? 'b' : 'a')));
  $('chart-description').textContent = state.metric === 'wealth' ? 'Wealth begins at 1 at the first common close. Today’s weights are replayed through the full available history.' : 'Drawdown is the decline from the highest wealth value reached so far, including initial capital.';
  for (const metric of ['wealth', 'drawdown']) {$(`${metric}-tab`).classList.toggle('selected', state.metric === metric); $(`${metric}-tab`).setAttribute('aria-pressed', String(state.metric === metric));}
}
function tables(value) {
  const analysis = value.analysis, portfolios = analysis.scenarios;
  const riskHeading = element('tr'), stressHeading = element('tr');
  riskHeading.append(element('th', 'Holding')); stressHeading.append(element('th', 'Window'));
  portfolios.forEach((portfolio, index) => {
    const prefix = portfolios.length === 1 ? '' : `${index ? 'Alternative' : 'Current'} `;
    riskHeading.append(element('th', `${prefix}weight`), element('th', `${prefix}risk share`));
    stressHeading.append(element('th', `${prefix}replay return`), element('th', `${prefix}drawdown`));
  });
  $('risk-heading').replaceChildren(riskHeading); $('stress-heading').replaceChildren(stressHeading);
  $('risk-rows').replaceChildren(...analysis.symbols.map((symbol, i) => {
    const row = element('tr');
    row.append(element('td', symbol));
    for (const portfolio of portfolios) row.append(element('td', percent(portfolio.weights[i])), element('td', percent(portfolio.risk_shares[i])));
    return row;
  }));
  const scenarios = [...new Set(value.historical_scenarios.map(row => row.scenario_id))];
  $('stress-rows').replaceChildren(...scenarios.map(id => {
    const rows = value.historical_scenarios.filter(row => row.scenario_id === id), row = element('tr');
    const name = element('td', rows[0].name); name.append(element('span', `${rows[0].start_close} → ${rows[0].end_close}`, 'secondary-text')); row.append(name);
    for (const portfolio of portfolios) {
      const item = rows.find(r => r.portfolio_id === portfolio.id);
      for (const key of ['replay_return', 'maximum_drawdown']) {
        const cell = element('td', item.available ? percent(item[key]) : 'Unavailable');
        if (!item.available) cell.title = item.reason;
        row.append(cell);
      }
    }
    return row;
  }));
  const table = $('correlation-table'); table.replaceChildren();
  const head = element('thead'), header = element('tr');
  header.append(element('th', 'Correlation')); analysis.symbols.forEach(symbol => header.append(element('th', symbol))); head.append(header); table.append(head);
  const body = element('tbody');
  analysis.symbols.forEach((symbol, i) => {
    const row = element('tr'); row.append(element('td', symbol));
    analysis.symbols.forEach((_, j) => {const v = analysis.correlation[i][j]; row.append(element('td', v === null ? 'Undefined' : v.toFixed(2), v < 0 ? 'negative' : 'positive'));});
    body.append(row);
  }); table.append(body);
}
function methods(value) {
  const a = value.analysis, notes = $('method-notes'); notes.replaceChildren();
  for (const text of [
    `Volatility and correlations use sample covariance (N−1), annualized by 252, over ${a.risk_window_sessions} common returns: ${a.risk_window_start} through ${a.risk_window_end}.`,
    `Full-history drawdown and the replay chart cover ${a.history_start} through ${a.history_end}. ${a.scenarios.length === 1 ? 'All displayed historical calculations use this portfolio snapshot.' : 'Both portfolios share these dates.'} Reported holdings are ${value.is_demo ? 'explicit demonstrations' : 'your entered scenarios'}, not evidence of actual historical investment performance.`,
    'Inputs are daily USD stocks and ETFs. Cash, leverage, taxes, transaction costs, currency conversion, and underlying ETF holdings overlap are not modeled.',
    `${state.context.source_issues.length} retained index-source exceptions remain outside portfolio calculations. Neither FRED context nor the quarantined Yahoo index is used to calculate these portfolio results.`,
    'Saved adjusted price histories may be revised. This page uses a stored research snapshot and does not download live prices or use trained-model forecasts.'
  ]) notes.append(element('p', text));
  const identity = element('p', 'Dataset: '); identity.append(element('code', a.recipe.dataset_id)); notes.append(identity);
  const report = element('p', 'Analysis: '); report.append(element('code', a.report_id)); notes.append(report);
  const provisional = (value.source_validation || []).filter(row => row.policy === 'AP-001');
  if (provisional.length) notes.prepend(element('p', `On-demand sources: ${provisional.map(row => row.symbol).join(', ')} passed structural/provider-metadata checks under AP-001 but have not been independently price-cross-checked. Their saved evidence is separate from the fixed sixteen-instrument model dataset.`, 'notice error'));
}
async function runAnalysis(event) {
  if (event) event.preventDefault();
  $('form-error').hidden = true; $('analyze').disabled = true; $('analyze').textContent = 'Checking and calculating…'; $('results').setAttribute('aria-busy', 'true');
  try {
    const revision = state.revision;
    const value = await api('/api/analyze', requestPayload()); state.result = value;
    const provisional = (value.source_validation || []).filter(row => row.policy === 'AP-001');
    $('source-status').hidden = !provisional.length;
    $('source-status').textContent = provisional.length ? `${provisional.map(row => row.symbol).join(', ')}: provider identity and structural checks passed; independent price cross-checks have not been performed. Source warnings are retained in the exported report.` : '';
    $('results').classList.remove('stale'); $('result-content').hidden = false;
    const single = value.analysis.scenarios.length === 1;
    $('result-title').textContent = value.is_demo ? (single ? 'Demonstration risk report' : 'Demonstration comparison') : (single ? 'Your risk report' : 'Portfolio comparison');
    $('result-context').textContent = `${value.analysis.risk_window_sessions}-session risk estimate ending ${shortDate(value.analysis.risk_window_end)} · historical, not a forecast`;
    metricCards(value); preferenceSummary(value); drawChart(); tables(value); methods(value); $('download').disabled = false;
    if (revision !== state.revision) {
      $('results').classList.add('stale');
      $('result-context').textContent = 'Inputs changed during calculation. Run analysis again to refresh.';
      $('download').disabled = true;
    } else {
      renderReweightControls(value);
    }
  } catch (error) {$('form-error').textContent = error.message; $('form-error').hidden = false;}
  finally {$('analyze').disabled = false; buttonLabel(); $('results').setAttribute('aria-busy', 'false');}
}
let reweightRequest = 0;
let reweightScenario = null;

function clearReweightPreview() {
  reweightRequest += 1;
  reweightScenario = null;
  $('reweight-preview').hidden = true;
  $('reweight-error').hidden = true;
  clearReplacementCriteria();
}

function renderReweightControls(value) {
  clearReweightPreview();
  const {symbols, scenarios} = value.analysis;
  const rows = symbols.flatMap((symbol, index) => {
    if (scenarios[0].weights[index] <= 0) return [];
    const row = element('tr');
    row.dataset.symbol = symbol;
    row.append(element('td', symbol));
    for (const [label, initial] of [['minimum', '0'], ['maximum', '100'], ['lock', null]]) {
      const input = element('input');
      input.setAttribute('aria-label', `${symbol} ${label}`);
      input.name = label;
      if (initial === null) input.type = 'checkbox';
      else {
        input.type = 'number'; input.min = '0'; input.max = '100';
        input.step = 'any'; input.required = true; input.value = initial;
      }
      const cell = element('td'); cell.append(input); row.append(cell);
    }
    return [row];
  });
  $('reweight-constraints').replaceChildren(...rows);
  $('reweight-card').hidden = rows.length === 0;
  $('preview-reweight').hidden = rows.length < 2;
  $('replace-symbol').replaceChildren(...rows.map(row => {
    const option = element('option', row.dataset.symbol);
    option.value = row.dataset.symbol;
    return option;
  }));
  $('replace-weight').value = '';
}

function showReweight(value) {
  const status = {
    already_within_target: 'The current estimate is already within your target.',
    no_improvement: 'The allowed changes do not materially lower the estimate.',
    lower_risk: 'This scenario lowers estimated historical volatility.',
    target_unreachable: 'The target is out of reach under these limits. Here is the lowest estimated risk found.',
    target_met: 'This scenario reaches your historical volatility target.',
  };
  $('reweight-summary').textContent = `${status[value.status]} Historical volatility ${percent(value.current_volatility)} → ${percent(value.alternative_volatility)}. Maximum drawdown ${percent(value.current_drawdown)} → ${percent(value.alternative_drawdown)}. Largest weight ${percent(value.current_largest_weight)} → ${percent(value.alternative_largest_weight)}. Portfolio value moved ${percent(value.turnover)} of ${percent(value.turnover_limit)} allowed.`;
  $('reweight-rows').replaceChildren(...value.holdings.map(holding => {
    const row = element('tr');
    row.append(element('td', holding.symbol));
    for (const key of ['current_weight', 'alternative_weight', 'current_risk_share', 'alternative_risk_share']) {
      row.append(element('td', percent(holding[key])));
    }
    return row;
  }));
  $('use-reweight').hidden = value.turnover === 0;
  $('reweight-preview').hidden = false;
  reweightScenario = value;
}

function allocationConstraints() {
  const holdings = Object.fromEntries(Array.from($('reweight-constraints').rows, row => [
    row.dataset.symbol, {
      minimum: Number(row.querySelector('[name=minimum]').value) / 100,
      maximum: Number(row.querySelector('[name=maximum]').value) / 100,
      locked: row.querySelector('[name=lock]').checked,
    },
  ]));
  return {turnover_limit: Number($('turnover-limit').value) / 100, holdings};
}

let replacementRequest = 0;

function clearReplacementCriteria() {
  replacementRequest += 1;
  $('replacement-result').hidden = true;
  $('replacement-screen').hidden = true;
  $('replacement-error').hidden = true;
}

$('replacement-form').addEventListener('input', clearReplacementCriteria);
$('replacement-form').addEventListener('submit', async event => {
  event.preventDefault();
  clearReplacementCriteria();
  const request = replacementRequest;
  const screen = event.submitter?.id === 'screen-replacement';
  $('show-replacement').disabled = true;
  $('screen-replacement').disabled = true;
  try {
    const reweightForm = $('reweight-form');
    if (!reweightForm.reportValidity()) return;
    const result = await api(screen ? '/api/replacement-screen' : '/api/replacement-criteria', {
      portfolio: requestPayload(false),
      constraints: allocationConstraints(),
      replacement: {symbol: $('replace-symbol').value, weight: Number($('replace-weight').value) / 100},
    });
    if (request !== replacementRequest) return;
    const basis = result.target_source === 'manual_reference' ? 'your manual reference' : 'the current portfolio estimate';
    $('replacement-summary').textContent = `Replace ${percent(result.replacement_weight)} of portfolio value from ${result.symbol}. The historical volatility target is ${percent(result.target)}, based on ${basis}. Compare candidates over the same ${result.risk_window_sessions} sessions ending ${shortDate(result.risk_window_end)}.`;
    $('replacement-bands').replaceChildren(...result.bands.map(({correlation, volatility}) => {
      const row = element('tr');
      let range = 'No feasible range';
      if (volatility) range = volatility.minimum > 0
        ? `${percent(volatility.minimum)} to ${percent(volatility.maximum)}`
        : `Up to ${percent(volatility.maximum)}`;
      row.append(element('td', correlation === null ? 'Remaining holdings have zero measured volatility' : correlation.toFixed(2)),
                 element('td', range));
      return row;
    }));
    $('replacement-result').hidden = false;
    if (result.screen) showReplacementScreen(result);
  } catch (error) {
    if (request === replacementRequest) {
      $('replacement-error').textContent = error.message;
      $('replacement-error').hidden = false;
    }
  } finally {
    $('show-replacement').disabled = false;
    $('screen-replacement').disabled = false;
  }
});

function showReplacementScreen(result) {
  const {candidates, policy, universe_id} = result.screen;
  const eligible = candidates.filter(row => row.status === 'meets_target').length;
  $('replacement-screen-summary').textContent = `${eligible} of ${candidates.length} candidates meet the target using the ${universe_id} list and ${policy} price evidence.`;
  $('replacement-candidates').replaceChildren(...candidates.map(candidate => {
    const row = element('tr'), name = element('td', candidate.symbol), action = element('td');
    name.append(element('span', candidate.research_role, 'secondary-text'));
    const status = {meets_target: 'Meets target', above_target: 'Above target', unavailable: 'Incomplete matched history'};
    if (candidate.status === 'meets_target') {
      const button = element('button', 'Compare', 'secondary-button');
      button.type = 'button';
      button.setAttribute('aria-label', `Compare ${candidate.symbol} replacement`);
      button.addEventListener('click', () => {
        const source = state.positions.find(position => position.symbol === result.symbol);
        const remainder = Math.max(0, (source.a / 100 - result.replacement_weight) * 100);
        const count = state.positions.filter(position => position.a > 0 && position !== source).length + 1;
        if (count + Number(remainder > 0) > 100) {
          $('replacement-error').textContent = 'The alternative would exceed 100 positions. Choose a full replacement or reduce the holding count.';
          $('replacement-error').hidden = false;
          return;
        }
        copyCurrentWeights();
        source.b = remainder;
        let destination = state.positions.find(position => position.symbol === candidate.symbol);
        if (!destination) {
          destination = {symbol: candidate.symbol, a: 0, b: 0};
          state.positions.push(destination);
        }
        destination.b = result.replacement_weight * 100;
        openAlternative(`Replacement scenario · ${candidate.symbol}`);
      });
      action.append(button);
    }
    row.append(name, element('td', percent(candidate.standalone_volatility)),
               element('td', candidate.correlation == null ? '—' : candidate.correlation.toFixed(2)),
               element('td', percent(candidate.portfolio_volatility)), element('td', status[candidate.status]), action);
    return row;
  }));
  $('replacement-screen').hidden = false;
}

$('reweight-form').addEventListener('input', clearReweightPreview);
$('reweight-form').addEventListener('submit', async event => {
  event.preventDefault();
  clearReweightPreview();
  const request = reweightRequest;
  $('preview-reweight').disabled = true;
  try {
    const result = await api('/api/reweight', {portfolio: requestPayload(false), constraints: allocationConstraints()});
    if (request === reweightRequest) showReweight(result);
  } catch (error) {
    if (request === reweightRequest) {
      $('reweight-error').textContent = error.message;
      $('reweight-error').hidden = false;
    }
  } finally {
    $('preview-reweight').disabled = false;
  }
});
$('use-reweight').addEventListener('click', () => {
  if (!reweightScenario) return;
  const weights = new Map(reweightScenario.holdings.map(row => [row.symbol, row.alternative_weight * 100]));
  state.positions.forEach(position => {position.b = weights.get(position.symbol) ?? 0;});
  openAlternative('Reweighted scenario');
});

function openAlternative(name) {
  $('name-b').value = name;
  state.compare = true;
  state.alternativeInitialized = true;
  renderPositions();
  dirty();
  runAnalysis();
}

$('portfolio-form').addEventListener('submit', runAnalysis);
$('compare-mode').addEventListener('change', () => {
  state.compare = $('compare-mode').checked;
  if (state.compare && !state.alternativeInitialized) copyCurrentWeights();
  renderPositions(); dirty();
});
$('copy-weights').addEventListener('click', () => {copyCurrentWeights(); renderPositions(); dirty();});
for (const id of ['name-a', 'name-b', 'as-of', 'risk-window', 'vol-reference']) $(id).addEventListener('input', dirty);
$('add-position').addEventListener('click', addSymbol);
$('add-symbol').addEventListener('input', () => {clearTimeout(searchTimer); searchTimer = setTimeout(searchSymbols, 180);});
$('add-symbol').addEventListener('keydown', event => {if (event.key === 'Enter') {event.preventDefault(); addSymbol();}});
$('load-demo').addEventListener('click', () => {loadDemo(); runAnalysis();});
for (const metric of ['wealth', 'drawdown']) $(`${metric}-tab`).addEventListener('click', () => {state.metric = metric; drawChart();});
$('download').addEventListener('click', () => {
  if (!state.result) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(state.result, null, 2)], {type: 'application/json'}));
  const link = element('a'); link.href = url; link.download = `portfolio-risk-${state.result.analysis.history_end}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
async function initialize() {
  try {
    state.context = await api('/api/context');
    const catalog = state.context.symbol_catalog;
    $('snapshot').textContent = `${catalog ? catalog.eligible_candidates.toLocaleString() + ' searchable U.S. stock/ETF candidates' : state.context.instruments.length + ' accepted instruments'} · saved analysis cutoff ${shortDate(state.context.latest_common_close)} · USD`;
    const research = state.context.research_scorecard;
    if (research) {
      $('research-scorecard').hidden = false;
      $('research-rows').replaceChildren(...[2023, 2024, 2025].map(year => {
        const row = element('tr'); row.append(element('td', String(year)));
        for (const method of [research.selected_model, research.selected_ewma, 'trailing_20']) {
          const score = research.metrics.find(r => r.year === year && r.method === method);
          row.append(element('td', score.volatility_mae_pp.toFixed(2)));
        }
        return row;
      }));
      const qlike = [research.selected_model, research.selected_ewma, 'trailing_20'].map(method => research.metrics.find(r => r.year === 2025 && r.method === method).variance_qlike.toFixed(4));
      $('research-secondary').textContent = `MAE is annualized-volatility error in percentage points. Lower is better. 2025 secondary variance QLIKE: model ${qlike[0]}, EWMA ${qlike[1]}, trailing ${qlike[2]}. Each primary comparison uses 192 correlated instrument/window pairs.`;
    }
    $('as-of').min = state.context.earliest_common_close; $('as-of').max = state.context.latest_common_close;
    $('workspace').hidden = false; questionnaireFields(); loadDemo(); await runAnalysis();
  } catch (error) {$('fatal-error').textContent = error.message; $('fatal-error').hidden = false; $('snapshot').textContent = 'Local data is unavailable.';}
}
initialize();
