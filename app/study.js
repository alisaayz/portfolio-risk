'use strict';

const byId = id => document.getElementById(id);
let definition;
let participantId;

function node(tag, text) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  return element;
}

async function request(path, payload) {
  const response = await fetch(path, payload === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'The study request failed.');
  return value;
}

function showError(error) {
  byId('study-error').textContent = error.message;
  byId('study-error').hidden = false;
}

function drawBars() {
  const measure = byId('chart-measure').value;
  const svg = byId('chart-bars');
  svg.replaceChildren();
  svg.setAttribute('aria-label', measure === 'risk_share_pct' ? 'Share of volatility by holding' : 'Capital weight by holding');
  const ns = 'http://www.w3.org/2000/svg';
  definition.report.holdings.forEach((holding, index) => {
    const y = index * 39 + 10;
    const bar = document.createElementNS(ns, 'rect');
    const label = document.createElementNS(ns, 'text');
    const value = document.createElementNS(ns, 'text');
    bar.setAttribute('x', '52');
    bar.setAttribute('y', String(y));
    bar.setAttribute('width', String(2.25 * holding[measure]));
    bar.setAttribute('height', '19');
    label.setAttribute('y', String(y + 14));
    label.textContent = holding.symbol;
    value.setAttribute('x', '285');
    value.setAttribute('y', String(y + 14));
    value.textContent = `${holding[measure].toFixed(2)}%`;
    svg.append(label, bar, value);
  });
}

function showTask(variant) {
  const report = definition.report;
  byId('report-dates').textContent = `${report.risk_sessions} trading sessions ending ${report.as_of} for volatility. Drawdown covers ${report.drawdown_start} through ${report.as_of}.`;
  const facts = [
    ['Annualized historical volatility', report.volatility_pct],
    ['Example volatility reference', report.reference_pct],
    ['Maximum historical drawdown', report.drawdown_pct],
  ];
  for (const [label, value] of facts) {
    const row = node('div');
    row.append(node('dt', label), node('dd', `${value.toFixed(2)}%`));
    byId('study-facts').append(row);
  }
  for (const holding of report.holdings) {
    const row = node('tr');
    row.append(node('td', holding.symbol), node('td', `${holding.weight_pct.toFixed(2)}%`),
               node('td', `${holding.risk_share_pct.toFixed(2)}%`));
    byId('study-holdings').append(row);
  }
  if (variant === 'visual') {
    byId('study-chart').hidden = false;
    drawBars();
  }
  definition.questions.forEach((question, index) => {
    const fieldset = node('fieldset');
    fieldset.append(node('legend', `${index + 1}. ${question.prompt}`));
    for (const [value, text] of Object.entries(question.choices)) {
      const label = node('label');
      const input = node('input');
      input.type = 'radio';
      input.name = question.id;
      input.value = value;
      input.required = true;
      label.append(input, node('span', text));
      fieldset.append(label);
    }
    byId('study-questions').append(fieldset);
  });
  byId('study-task').hidden = false;
}

function showReceipt(receipt) {
  byId('study-task').hidden = true;
  byId('study-start').hidden = true;
  const completed = receipt.status === 'completed';
  byId('done-title').textContent = completed ? 'Questions complete' : 'Session ended';
  byId('done-detail').textContent = definition.recording ? 'Your study session has been recorded locally.' : 'Practice is complete.';
  if (receipt.answers?.length) {
    byId('done-detail').textContent += ` ${receipt.answers.filter(item => item.correct).length} of 3 correct.`;
    for (const item of receipt.answers) byId('study-feedback').append(node('li', item.explanation));
  }
  byId('practice-again').hidden = definition.recording;
  byId('study-done').hidden = false;
}

async function start() {
  const payload = {participant_id: participantId, consent: true};
  if (!definition.recording) payload.variant = byId('practice-format').value;
  const assigned = await request('/api/study/start', payload);
  byId('study-start').hidden = true;
  if (assigned.status === 'started') showTask(assigned.variant);
  else showReceipt(assigned);
}

async function finish(answers) {
  byId('study-error').hidden = true;
  byId('submit-answers').disabled = true;
  byId('end-study').disabled = true;
  try {
    showReceipt(await request('/api/study/finish', {participant_id: participantId, answers}));
  } catch (error) {
    showError(error);
  } finally {
    byId('submit-answers').disabled = false;
    byId('end-study').disabled = false;
  }
}

byId('start-form').addEventListener('submit', async event => {
  event.preventDefault();
  byId('study-error').hidden = true;
  byId('start-button').disabled = true;
  try {
    if (definition.recording) sessionStorage.setItem(definition.study_id, participantId);
    await start();
  } catch (error) {
    showError(error);
  } finally {
    byId('start-button').disabled = false;
  }
});
byId('answer-form').addEventListener('submit', event => {
  event.preventDefault();
  finish(Object.fromEntries(new FormData(event.currentTarget)));
});
byId('end-study').addEventListener('click', () => finish(null));
byId('chart-measure').addEventListener('change', drawBars);

async function initializeStudy() {
  try {
    definition = await request('/api/study');
    const existing = definition.recording ? sessionStorage.getItem(definition.study_id) : null;
    participantId = existing || crypto.randomUUID().replaceAll('-', '');
    byId('study-mode').textContent = definition.recording ? 'Recorded report study' : 'Practice preview';
    byId('study-privacy').textContent = definition.recording
      ? 'If you choose to participate, the app randomly assigns a report format and saves an anonymous session ID, your answers, timing, and completion status to the local pilot database. You can end the session at any time.'
      : 'Choose either report format to try the same three questions. Practice responses are discarded after scoring.';
    byId('format-label').hidden = definition.recording;
    byId('consent-text').textContent = definition.recording ? 'I agree to take part in this local study.' : 'I want to try the practice questions.';
    if (existing) await start();
    else byId('study-start').hidden = false;
  } catch (error) {
    showError(error);
  }
}
initializeStudy();
