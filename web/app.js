'use strict';
const $ = (selector) => document.querySelector(selector);
let allPatients = [];
let selectedPatient = null;
let requestId = 0;
const titles = {
  explorer: ['Patient explorer', 'A clearer view of the records, signals, and stories in your demo dataset.'],
  assistant: ['AI assistant', 'Ask a question. Follow the tools. Understand the demonstration data.'],
  schema: ['Database schema', 'Explore the structure behind every answer in the workspace.']
};
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}
function initials(name) { return name.split(' ').map(word => word[0]).slice(0, 2).join(''); }
function showPanel(name) {
  document.querySelectorAll('.panel').forEach(panel => { panel.hidden = panel.id !== name; });
  document.querySelectorAll('[data-panel]').forEach(button => {
    const active = button.dataset.panel === name;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  });
  $('#page-title').textContent = titles[name][0];
  $('#breadcrumb').textContent = titles[name][0];
  $('#page-description').textContent = titles[name][1];
}
async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The request could not be completed. Please try again.');
  return data;
}
function showError(error) { $('#global-error').textContent = error.message; $('#global-error').hidden = false; }
function renderPatients() {
  const term = $('#search').value.toLowerCase().trim();
  const filtered = allPatients.filter(p => `${p.name} ${p.patient_id}`.toLowerCase().includes(term));
  const list = $('#patient-list'); list.replaceChildren();
  $('#directory-count').textContent = String(filtered.length);
  if (!filtered.length) list.append(element('p', 'empty', 'No demo patients match your search.'));
  filtered.forEach(patient => {
    const button = element('button', `patient-item${patient.patient_id === selectedPatient ? ' selected' : ''}`);
    button.type = 'button'; button.setAttribute('aria-pressed', String(patient.patient_id === selectedPatient));
    const avatar = element('span', 'avatar', initials(patient.name));
    const info = element('span'); info.append(element('span', 'patient-name', patient.name), element('span', 'patient-meta', `${patient.age} years · ${patient.gender === 'F' ? 'Female' : 'Male'} · #${String(patient.patient_id).padStart(3, '0')}`));
    button.append(avatar, info, element('span', 'patient-arrow', '›'));
    button.addEventListener('click', () => selectPatient(patient.patient_id)); list.append(button);
  });
}
function riskPill(level, suffix = 'RISK') { return element('span', `risk-pill risk-${level.toLowerCase()}`, `${level} ${suffix}`); }
function metric(value, label) { const box = element('div', 'metric'); box.append(element('strong', '', value), element('span', '', label)); return box; }
function caption(title, tool) { const cap = element('div', 'section-caption'); cap.append(element('h2', '', title), element('code', '', tool)); return cap; }
async function selectPatient(id) {
  selectedPatient = id; renderPatients(); const current = ++requestId;
  $('#patient-detail').replaceChildren(element('div', 'card loading', 'Reading demonstration profile…'));
  try {
    const data = await api(`/api/patients/${id}`);
    if (current !== requestId) return;
    const risk = data.risk, readmission = data.readmission, patient = risk.patient;
    const profile = element('section', 'card profile'), top = element('div', 'profile-top'), names = element('div');
    names.append(element('h2', '', patient.name), element('p', 'profile-id', `DEMO PATIENT #${String(id).padStart(3, '0')}`));
    top.append(element('span', 'avatar', initials(patient.name)), names, riskPill(risk.risk_tier));
    const demographics = element('div', 'demographics');
    [['Age', `${patient.age} years`], ['Gender', patient.gender === 'F' ? 'Female' : 'Male'], ['Blood type', patient.blood_type]].forEach(([label, value]) => {
      const block = element('div'); block.append(element('span', '', label), element('strong', '', value)); demographics.append(block);
    });
    profile.append(top, demographics);
    const signals = element('section', 'card insight-card'); signals.append(caption('Risk signals', 'patient_risk_summary'));
    const metrics = element('div', 'metric-grid'); metrics.append(metric(risk.risk_factors.chronic_condition_count, 'Chronic conditions'), metric(risk.risk_factors.active_medication_count, 'Active medications'), metric(risk.risk_factors.abnormal_lab_count, 'Abnormal latest labs'));
    signals.append(metrics, element('div', 'signal-note', `${risk.scoring.total_signals} combined scoring signals · ${risk.scoring.chronic_signal} chronic + ${risk.scoring.polypharmacy_signal} medication burden + ${risk.risk_factors.abnormal_lab_count} lab signals`));
    if (risk.risk_factors.abnormal_labs.length) {
      signals.append(element('div', 'lab-heading', 'LATEST ABNORMAL LAB RESULTS'));
      const table = element('table', 'lab-table'); table.setAttribute('aria-label', 'Latest abnormal laboratory results'); const tbody = element('tbody');
      risk.risk_factors.abnormal_labs.forEach(lab => { const row = element('tr'); row.append(element('td', '', lab.test_name), element('td', '', `${lab.result_value} ${lab.unit || ''}`)); tbody.append(row); }); table.append(tbody); signals.append(table);
    }
    const visits = element('section', 'card insight-card'); const visitTitle = caption('Readmission insights', 'readmission_insights'); visitTitle.append(riskPill(readmission.readmission_risk)); visits.append(visitTitle);
    const windows = element('div', 'visits'); [[readmission.visit_counts.last_30_days, 'Last 30 days'], [readmission.visit_counts.last_90_days, 'Last 90 days'], [readmission.visit_counts.last_180_days, 'Last 180 days']].forEach(([count, label]) => { const item = element('div'); item.append(element('strong', '', count), element('span', '', label)); windows.append(item); });
    visits.append(windows, element('p', 'readmission-summary', readmission.summary), element('p', 'muted', 'Visit dates are historical demo records. Recent-visit windows use today’s date.'));
    $('#patient-detail').replaceChildren(profile, signals, visits);
  } catch (error) { if (current === requestId) $('#patient-detail').replaceChildren(element('div', 'card error', error.message)); }
}
function renderSchema(data) {
  const target = $('#schema-tables'); target.replaceChildren();
  Object.entries(data.tables).forEach(([name, info]) => {
    const card = element('section', 'card schema-card'), heading = element('h2', '', name); heading.append(element('span', '', `${info.row_count} rows`)); card.append(heading);
    const table = element('table'); table.setAttribute('aria-label', `${name} columns`); const tbody = element('tbody');
    info.columns.forEach(column => { const row = element('tr'); row.append(element('td', '', `${column.column}${column.primary_key ? ' · PK' : ''}`), element('td', '', column.type)); tbody.append(row); }); table.append(tbody); card.append(table); target.append(card);
  });
}
document.querySelectorAll('[data-panel]').forEach(button => button.addEventListener('click', () => showPanel(button.dataset.panel)));
$('#search').addEventListener('input', renderPatients);
document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => { $('#question').value = button.dataset.question; $('#question').focus(); }));
$('#ask-form').addEventListener('submit', async event => {
  event.preventDefault(); $('#global-error').hidden = true;
  const button = $('#ask-button'); button.disabled = true; button.textContent = 'Reading demo data…';
  $('#answer-region').hidden = false; $('#answer').textContent = 'The assistant is consulting the MCP tools. This can take a few moments.'; $('#tools-used').replaceChildren();
  try {
    const result = await api('/api/ask', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Demo-Access-Code': $('#access-code').value}, body: JSON.stringify({question: $('#question').value.trim()})});
    $('#answer').textContent = result.answer;
    [...new Set(result.tools_used)].forEach(tool => $('#tools-used').append(element('span', 'tool-chip', tool)));
  } catch (error) { $('#answer').textContent = error.message; }
  finally { button.disabled = false; button.textContent = 'Ask assistant →'; }
});
async function initialize() {
  try {
    const [health, patients, schema] = await Promise.all([api('/api/health'), api('/api/patients'), api('/api/schema')]);
    $('#connection').textContent = 'MCP connected'; $('#model-label').textContent = health.model;
    allPatients = patients.patients; $('#patient-count').textContent = String(allPatients.length); $('#visit-count').textContent = String(schema.tables.visits.row_count);
    renderPatients(); renderSchema(schema); if (allPatients.length) await selectPatient(allPatients[0].patient_id);
  } catch (error) { $('#connection').textContent = 'Connection issue'; showError(error); }
}
initialize();
