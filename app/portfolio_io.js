'use strict';

const draftKey = 'riskitnot.v2.portfolioDraft';
const maxCsvBytes = 65536;
let importRows = null;
let previewGeneration = 0;

function validateWeights(rows) {
  if (!Array.isArray(rows) || rows.length < 1 || rows.length > 100) {
    throw new Error('Enter between 1 and 100 holdings.');
  }
  const known = new Set(state.context.instruments.map(row => row.symbol));
  const seen = new Set();
  let total = 0;
  for (const row of rows) {
    if (!row || typeof row.symbol !== 'string' || !/^[A-Z][A-Z0-9.-]{0,15}$/.test(row.symbol)) {
      throw new Error('Each holding needs a valid ticker.');
    }
    if (seen.has(row.symbol)) throw new Error(`Duplicate ticker ${row.symbol}. Combine its rows first.`);
    if (!known.has(row.symbol)) throw new Error(`${row.symbol} has no history loaded in this session. Use Add before continuing.`);
    if (!Number.isFinite(row.a) || row.a <= 0 || row.a > 100) {
      throw new Error(`${row.symbol} needs a positive weight at or below 100%.`);
    }
    seen.add(row.symbol);
    total += row.a;
  }
  if (Math.abs(total - 100) > 1e-8) throw new Error(`Weights must total 100%. The total is ${total.toFixed(6)}%.`);
  return rows;
}

function readPortfolioCsv(csv) {
  const lines = csv.replace(/^\uFEFF/, '').split(/\r\n|\n|\r/).map(line => line.trim()).filter(Boolean);
  if (lines.length < 2 || lines.length > 101) throw new Error('Enter a header and 1 to 100 holding rows.');
  const records = lines.map((line, index) => {
    const pair = line.match(/^("[^",]*"|[^",]*)\s*,\s*("[^",]*"|[^",]*)$/);
    if (!pair) throw new Error(`Row ${index + 1} must have two columns. Use plain numbers without commas or currency signs.`);
    return pair.slice(1).map(cell => cell.trim().replace(/^"(.*)"$/, '$1').trim());
  });
  const [[ticker, unit], ...body] = records;
  if (ticker !== 'ticker' || !['weight', 'market_value'].includes(unit)) {
    throw new Error('Use the header ticker,weight or ticker,market_value.');
  }
  const rows = body.map(([symbol, amount]) => {
    if (!/^(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)$/.test(amount) || !Number.isFinite(Number(amount)) || Number(amount) <= 0) {
      throw new Error(`${symbol || 'Each holding'} needs a positive decimal number.`);
    }
    return {symbol: symbol.toUpperCase(), a: Number(amount)};
  });
  if (unit === 'market_value') {
    const total = rows.reduce((sum, row) => sum + row.a, 0);
    if (!Number.isFinite(total)) throw new Error('The sum of market values is too large.');
    for (const row of rows) row.a = (row.a / total) * 100;
  }
  return validateWeights(rows);
}

function replaceCurrentWeights(rows) {
  validateWeights(rows);
  const updated = new Map(rows.map(row => [row.symbol, {symbol: row.symbol, a: row.a, b: 0}]));
  for (const row of state.positions) {
    if (state.alternativeInitialized && row.b !== 0) {
      if (!updated.has(row.symbol)) updated.set(row.symbol, {symbol: row.symbol, a: 0, b: 0});
      updated.get(row.symbol).b = row.b;
    }
  }
  state.positions = [...updated.values()];
  renderPositions();
  dirty();
}

function clearImport() {
  previewGeneration += 1;
  importRows = null;
  $('import-rows').replaceChildren();
  $('import-preview').hidden = true;
  $('import-error').hidden = true;
  $('import-status').textContent = '';
}

$('portfolio-csv').addEventListener('change', clearImport);
$('csv-text').addEventListener('input', clearImport);
$('preview-import').addEventListener('click', async () => {
  clearImport();
  const generation = previewGeneration;
  try {
    const file = $('portfolio-csv').files[0];
    const pasted = $('csv-text').value.trim();
    if (file && pasted) throw new Error('Choose a file or paste CSV text.');
    if ((file?.size ?? new Blob([pasted]).size) > maxCsvBytes) throw new Error('Use a CSV of at most 64 KiB.');
    const rows = readPortfolioCsv(file ? await file.text() : pasted);
    if (generation !== previewGeneration) return;
    importRows = rows;
    $('import-rows').replaceChildren(...rows.map(({symbol, a}) => {
      const row = element('tr');
      row.append(element('td', symbol), element('td', percent(a / 100)));
      return row;
    }));
    $('import-preview').hidden = false;
    $('import-status').textContent = `Preview ready for ${rows.length} holdings. Review the weights before applying.`;
    $('apply-import').focus();
  } catch (error) {
    if (generation !== previewGeneration) return;
    $('import-error').textContent = error.message;
    $('import-error').hidden = false;
  }
});

$('apply-import').addEventListener('click', () => {
  if (!importRows) return;
  replaceCurrentWeights(importRows);
  resetImport();
  $('import-status').textContent = 'Imported weights applied. Assess your portfolio to refresh the report.';
  $('analyze').focus();
});

function resetImport() {
  clearImport();
  $('portfolio-csv').value = '';
  $('csv-text').value = '';
}

$('cancel-import').addEventListener('click', () => {
  resetImport();
  $('preview-import').focus();
});

for (const action of ['save', 'open', 'delete']) {
  $(`${action}-draft`).addEventListener('click', () => {
    const status = $('draft-status');
    try {
      if (action === 'save') {
        const positions = requestPayload(false).configuration.portfolios[0].positions;
        const rows = validateWeights(positions.map(position => ({symbol: position.instrument_id, a: position.weight * 100})));
        localStorage.setItem(draftKey, JSON.stringify({version: 1, rows}));
        status.textContent = 'Current weights saved in this browser.';
      } else if (action === 'open') {
        const saved = JSON.parse(localStorage.getItem(draftKey));
        if (!saved) throw new Error('There is no saved draft in this browser.');
        if (saved.version !== 1) throw new Error('This draft format is unsupported.');
        replaceCurrentWeights(saved.rows);
        resetImport();
        status.textContent = 'Saved weights opened. Assess your portfolio to refresh the report.';
      } else {
        localStorage.removeItem(draftKey);
        status.textContent = 'Saved draft deleted. Your current entries are still open.';
      }
    } catch (error) {
      status.textContent = error instanceof SyntaxError ? 'The saved draft is unreadable. Delete it or save a new draft.' :
        error instanceof DOMException ? 'Browser draft storage is unavailable.' : error.message;
    }
  });
}

initialize();
