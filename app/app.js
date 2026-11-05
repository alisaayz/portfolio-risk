'use strict';

const $ = id => document.getElementById(id);
const state = {context: null, positions: [], result: null, demo: true, metric: 'wealth', revision: 0};
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
function renderPositions() {
  $('position-rows').replaceChildren();
  state.positions.forEach(position => {
    const row = element('tr');
    row.append(element('td', position.symbol));
    for (const key of ['a', 'b']) {
      const cell = element('td'), input = document.createElement('input');
      input.type = 'number'; input.min = '0'; input.max = '100'; input.step = 'any';
      input.value = String(position[key]);
      input.setAttribute('aria-label', `${position.symbol} weight in portfolio ${key.toUpperCase()}, percent`);
      input.addEventListener('input', () => {position[key] = input.value === '' ? 0 : Number(input.value); totals(); dirty();});
      cell.append(input); row.append(cell);
    }
    const cell = element('td'), remove = element('button', '×', 'remove-position');
    remove.type = 'button'; remove.setAttribute('aria-label', `Remove ${position.symbol}`);
    remove.addEventListener('click', () => {state.positions = state.positions.filter(p => p !== position); renderPositions(); dirty();});
    cell.append(remove); row.append(cell); $('position-rows').append(row);
  });
  $('add-symbol').replaceChildren();
  state.context.instruments.filter(i => !state.positions.some(p => p.symbol === i.symbol)).forEach(instrument => {
    const option = element('option', `${instrument.symbol} · ${instrument.label}`); option.value = instrument.symbol; $('add-symbol').append(option);
  });
  $('add-position').disabled = !$('add-symbol').options.length;
  totals();
}
function loadDemo() {
  state.revision += 1;
  const config = state.context.demo_configuration;
  $('name-a').value = config.portfolios[0].name;
  $('name-b').value = config.portfolios[1].name;
  $('as-of').value = config.as_of_date;
  $('risk-window').value = String(config.risk_window_sessions);
  $('vol-reference').value = '';
  const maps = config.portfolios.map(p => new Map(p.positions.map(v => [v.instrument_id, v.weight * 100])));
  const symbols = [...new Set(config.portfolios.flatMap(p => p.positions.map(v => v.instrument_id)))];
  state.positions = symbols.map(symbol => ({symbol, a: maps[0].get(symbol) || 0, b: maps[1].get(symbol) || 0}));
  state.demo = true; $('input-label').textContent = 'Demonstration holdings · edit to explore your own.';
  renderPositions();
}
function requestPayload() {
  const portfolios = ['a', 'b'].map(key => {
    if (state.positions.some(p => !Number.isFinite(p[key]) || p[key] < 0)) throw new Error('Use finite, nonnegative allocation percentages.');
    const positions = state.positions.filter(p => p[key] > 0).map(p => ({instrument_id: p.symbol, weight: p[key] / 100}));
    const total = positions.reduce((sum, p) => sum + p.weight, 0);
    if (!positions.length || Math.abs(total - 1) > 1e-10) throw new Error(`Portfolio ${key.toUpperCase()} must total 100%. Weights are not automatically rescaled.`);
    return {id: `portfolio_${key}`, name: $(`name-${key}`).value.trim(), input_type: 'weights', positions};
  });
  return {configuration: {schema_version: 1, is_demo: state.demo, as_of_date: $('as-of').value,
    report_currency: 'USD', risk_window_sessions: Number($('risk-window').value),
    convention: 'fixed_weights_daily_rebalanced', portfolios},
    volatility_reference: $('vol-reference').value === '' ? null : Number($('vol-reference').value) / 100};
}
function metricCards(value) {
  $('metrics').replaceChildren();
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
  const analysis = value.analysis, [a, b] = analysis.scenarios;
  $('risk-rows').replaceChildren(...analysis.symbols.map((symbol, i) => {
    const row = element('tr');
    for (const text of [symbol, percent(a.weights[i]), percent(a.risk_shares[i]), percent(b.weights[i]), percent(b.risk_shares[i])]) row.append(element('td', text));
    return row;
  }));
  const scenarios = [...new Set(value.historical_scenarios.map(row => row.scenario_id))];
  $('stress-rows').replaceChildren(...scenarios.map(id => {
    const rows = value.historical_scenarios.filter(row => row.scenario_id === id), row = element('tr');
    const name = element('td', rows[0].name); name.append(element('span', `${rows[0].start_close} → ${rows[0].end_close}`, 'secondary-text')); row.append(name);
    for (const portfolio of [a, b]) {
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
    `Full-history drawdown and the replay chart cover ${a.history_start} through ${a.history_end}. Both portfolios share these dates. Reported holdings are ${value.is_demo ? 'explicit demonstrations' : 'your entered scenarios'}, not evidence of actual historical investment performance.`,
    'Inputs are daily USD stocks and ETFs. Cash, leverage, taxes, transaction costs, currency conversion, and underlying ETF holdings overlap are not modeled.',
    `${state.context.source_issues.length} retained index-source exceptions remain outside portfolio calculations. Neither FRED context nor the quarantined Yahoo index is used to calculate these portfolio results.`,
    'Saved adjusted price histories may be revised. This page uses a stored research snapshot and does not download live prices or use trained-model forecasts.'
  ]) notes.append(element('p', text));
  const identity = element('p', 'Dataset: '); identity.append(element('code', a.recipe.dataset_id)); notes.append(identity);
  const report = element('p', 'Analysis: '); report.append(element('code', a.report_id)); notes.append(report);
}
async function runAnalysis(event) {
  if (event) event.preventDefault();
  $('form-error').hidden = true; $('analyze').disabled = true; $('analyze').textContent = 'Checking and calculating…'; $('results').setAttribute('aria-busy', 'true');
  try {
    const revision = state.revision;
    const value = await api('/api/analyze', requestPayload()); state.result = value;
    $('results').classList.remove('stale'); $('result-content').hidden = false;
    $('result-title').textContent = value.is_demo ? 'Demonstration comparison' : 'Your portfolio comparison';
    $('result-context').textContent = `${value.analysis.risk_window_sessions}-session risk estimate ending ${shortDate(value.analysis.risk_window_end)} · historical, not a forecast`;
    metricCards(value); drawChart(); tables(value); methods(value); $('download').disabled = false;
    if (revision !== state.revision) {
      $('results').classList.add('stale');
      $('result-context').textContent = 'Inputs changed during calculation. Run analysis again to refresh.';
      $('download').disabled = true;
    }
  } catch (error) {$('form-error').textContent = error.message; $('form-error').hidden = false;}
  finally {$('analyze').disabled = false; $('analyze').replaceChildren(document.createTextNode('Analyze portfolios '), element('span', '↗')); $('results').setAttribute('aria-busy', 'false');}
}
$('portfolio-form').addEventListener('submit', runAnalysis);
for (const id of ['name-a', 'name-b', 'as-of', 'risk-window', 'vol-reference']) $(id).addEventListener('input', dirty);
$('add-position').addEventListener('click', () => {const symbol = $('add-symbol').value; if (symbol) {state.positions.push({symbol, a: 0, b: 0}); renderPositions(); dirty();}});
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
    $('snapshot').textContent = `${state.context.instruments.length} accepted instruments · saved prices through ${shortDate(state.context.latest_common_close)} · USD`;
    $('as-of').min = state.context.earliest_common_close; $('as-of').max = state.context.latest_common_close;
    $('workspace').hidden = false; loadDemo(); await runAnalysis();
  } catch (error) {$('fatal-error').textContent = error.message; $('fatal-error').hidden = false; $('snapshot').textContent = 'Local data is unavailable.';}
}
initialize();
