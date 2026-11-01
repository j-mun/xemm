const state = {
  materials: [],
  records: [],
  selected: null,
  selectedRecord: null,
  revision: null,
  uploadPreview: null,
  uploadFiles: [],
  submissions: [],
  searchVersion: 0,
};

const byId = (id) => document.getElementById(id);
const materialSelect = byId('material');
const recordSelect = byId('record');
const revisionSelect = byId('revision');
const status = byId('status');
const detail = byId('record-detail');
const chart = byId('chart');

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { Accept: 'application/json', ...options.headers },
    ...options,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      message = (await response.json()).detail || message;
    } catch {}
    throw new Error(message);
  }
  return response.json();
}

function showStatus(message, failed = false) {
  status.textContent = message;
  status.classList.toggle('error', failed);
}

function addOptions(select, items, labelFor, valueFor, placeholder) {
  select.replaceChildren(new Option(placeholder, ''));
  for (const item of items) {
    select.add(new Option(labelFor(item), valueFor(item)));
  }
}

async function loadMaterials(query = '', searchVersion = null) {
  const result = await api(`/api/v1/materials?limit=1000&query=${encodeURIComponent(query)}`);
  if (searchVersion !== null && searchVersion !== state.searchVersion) return;
  state.materials = result.items;
  const uploadMaterial = byId('upload-material');
  if (uploadMaterial) {
    addOptions(
      uploadMaterial,
      result.items,
      (item) => `${item.name} (${item.id})`,
      (item) => item.id,
      'Choose a material',
    );
  }
  if (materialSelect) {
    const selected = materialSelect.value;
    addOptions(
      materialSelect,
      result.items,
      (item) => `${item.name} (${item.id})`,
      (item) => item.id,
      result.items.length ? query ? 'All matching materials' : 'All materials' : 'No materials found',
    );
    if (result.items.some((item) => item.id === selected)) {
      materialSelect.value = selected;
    }
  }
  const count = byId('catalog-count');
  if (count) count.textContent = `${result.total.toLocaleString()} materials`;
}

async function loadRecords(searchVersion = null) {
  const material = materialSelect.value;
  const query = byId('search').value.trim();
  const params = new URLSearchParams({ limit: '1000' });
  if (material) params.set('material_id', material);
  if (query) params.set('query', query);
  const result = await api(`/api/v1/records?${params}`);
  if (searchVersion !== null && searchVersion !== state.searchVersion) return;
  state.records = result.items;
  addOptions(
    recordSelect,
    result.items,
    (item) => `${item.name} · ${item.model}`,
    (item) => item.id,
    result.items.length ? 'Choose a record' : 'No records found',
  );
  recordSelect.disabled = result.items.length === 0;
  byId('catalog-count').textContent = `${result.total.toLocaleString()} records`;
  state.selected = null;
  state.selectedRecord = null;
  state.revision = null;
  revisionSelect.disabled = true;
  byId('plot-button').disabled = true;
  detail.hidden = true;
}

function appendDetailLink(container, label, href) {
  const link = document.createElement('a');
  link.textContent = label;
  link.href = href;
  link.target = '_blank';
  link.rel = 'noopener';
  container.append(link);
}

async function selectRecord() {
  const reference = state.records.find((item) => item.id === recordSelect.value);
  if (!reference) return;
  state.selected = reference;
  state.revision = null;
  const interpolation = byId('interpolation');
  interpolation.options[1].disabled = reference.model !== 'tabulated';
  if (reference.model !== 'tabulated') interpolation.value = 'linear';
  const record = await api(`/api/v1/records/${encodeURIComponent(reference.id)}`);
  const revs = await api(`/api/v1/records/${encodeURIComponent(reference.id)}/revisions`);
  const payload = record.record;
  state.selectedRecord = payload;
  const properties = {
    n: 'n + ik',
    e: 'Permittivity (ε)',
    k: 'Extinction coefficient (k)',
    n2: 'Nonlinear index (n²)',
  };
  let choices = ['n', 'e'];
  if (payload.model === 'tabulated') {
    choices = ({
      n: ['n', 'e', 'k'],
      nk: ['n', 'e', 'k'],
      e: ['e', 'n'],
      eps: ['e', 'n'],
      k: ['k'],
      n2: ['n2'],
    })[payload.data.type] || ['n'];
  }
  addOptions(
    byId('parameter'),
    choices,
    (parameter) => properties[parameter],
    (parameter) => parameter,
    'Choose a property',
  );
  byId('parameter').value = choices[0];
  addOptions(
    revisionSelect,
    revs.items,
    (item) => `Revision ${item.revision}${item.revision === record.current_revision ? ' (current)' : ''}`,
    (item) => String(item.revision),
    `Current (revision ${record.current_revision})`,
  );
  revisionSelect.disabled = false;
  detail.replaceChildren();
  const title = document.createElement('div');
  title.className = 'detail-title';
  title.textContent = `${reference.material_name} / ${payload.name}`;
  const meta = document.createElement('p');
  meta.className = 'detail-meta';
  const source = payload.metadata?.source || 'Source not specified';
  meta.textContent = `${payload.physics} · ${payload.model} · ${source} · SHA-256 ${record.payload_sha256}`;
  const links = document.createElement('div');
  links.className = 'detail-links';
  appendDetailLink(links, 'Record JSON', `/api/v1/records/${encodeURIComponent(reference.id)}`);
  appendDetailLink(links, 'Provenance', `/api/v1/records/${encodeURIComponent(reference.id)}/provenance`);
  appendDetailLink(links, 'Export JSON', `/api/v1/records/${encodeURIComponent(reference.id)}/export?format=json`);
  detail.append(title, meta, links);
  detail.hidden = false;
  byId('plot-button').disabled = false;
  showStatus('Record loaded. Choose a property and plot its spectrum.');
  await plotSpectrum();
}

function seriesPath(values, coordinates, coordinateBounds, bounds, width, height, margin) {
  const x = (coordinate) => {
    const fraction = coordinateBounds.max === coordinateBounds.min
      ? 0.5
      : (coordinate - coordinateBounds.min)
        / (coordinateBounds.max - coordinateBounds.min);
    return margin.left + fraction * (width - margin.left - margin.right);
  };
  const y = (value) => margin.top + (bounds.max - value) / (bounds.max - bounds.min || 1) * (height - margin.top - margin.bottom);
  return values.map((value, index) => `${index ? 'L' : 'M'}${x(coordinates[index]).toFixed(2)},${y(value).toFixed(2)}`).join(' ');
}

function drawSpectrum(real, imaginary, coordinates, parameter, xLabel) {
  const width = 960;
  const height = 460;
  const margin = { top: 24, right: 24, bottom: 58, left: 68 };
  const hasImaginary = parameter === 'n' || parameter === 'e';
  const plottedImaginary = hasImaginary ? imaginary : [];
  const all = [...real, ...plottedImaginary].filter(Number.isFinite);
  const coordinateBounds = {
    min: Math.min(...coordinates),
    max: Math.max(...coordinates),
  };
  if (!all.length || !Number.isFinite(coordinateBounds.min) || !Number.isFinite(coordinateBounds.max)) {
    throw new Error('Spectrum contains no finite values to plot.');
  }
  const rawMin = Math.min(...all);
  const rawMax = Math.max(...all);
  const pad = (rawMax - rawMin) * 0.08 || Math.max(Math.abs(rawMax) * 0.08, 0.1);
  const bounds = { min: rawMin - pad, max: rawMax + pad };
  chart.replaceChildren();
  const ns = 'http://www.w3.org/2000/svg';
  const line = (x1, y1, x2, y2, className) => {
    const node = document.createElementNS(ns, 'line');
    for (const [key, value] of Object.entries({ x1, y1, x2, y2, class: className })) {
      node.setAttribute(key, value);
    }
    chart.append(node);
  };
  const text = (x, y, value, className, anchor = 'middle') => {
    const node = document.createElementNS(ns, 'text');
    node.setAttribute('x', x);
    node.setAttribute('y', y);
    node.setAttribute('text-anchor', anchor);
    node.setAttribute('class', className);
    node.textContent = value;
    chart.append(node);
  };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  for (let tick = 0; tick <= 4; tick += 1) {
    const y = margin.top + plotHeight * tick / 4;
    const value = bounds.max - (bounds.max - bounds.min) * tick / 4;
    line(margin.left, y, width - margin.right, y, 'grid-line');
    text(margin.left - 10, y + 4, value.toPrecision(4), 'tick-label', 'end');
  }
  for (let tick = 0; tick <= 5; tick += 1) {
    const x = margin.left + plotWidth * tick / 5;
    const value = coordinateBounds.min
      + (coordinateBounds.max - coordinateBounds.min) * tick / 5;
    line(x, margin.top, x, height - margin.bottom, 'grid-line');
    text(x, height - margin.bottom + 22, value.toPrecision(4), 'tick-label');
  }
  line(margin.left, margin.top, margin.left, height - margin.bottom, 'axis-line');
  line(margin.left, height - margin.bottom, width - margin.right, height - margin.bottom, 'axis-line');
  const axisLabels = {
    n: 'n, k',
    e: 'ε₁, ε₂',
    k: 'k',
    n2: 'n₂',
  };
  text(18, height / 2, axisLabels[parameter], 'axis-label');
  text(width / 2, height - 12, xLabel, 'axis-label');
  const path = (d, className) => {
    const node = document.createElementNS(ns, 'path');
    node.setAttribute('d', d);
    node.setAttribute('class', className);
    chart.append(node);
  };
  path(seriesPath(real, coordinates, coordinateBounds, bounds, width, height, margin), 'series-real');
  if (hasImaginary) {
    path(seriesPath(plottedImaginary, coordinates, coordinateBounds, bounds, width, height, margin), 'series-imag');
  }
  if (coordinates.length === 1) {
    const point = (value, className) => {
      const circle = document.createElementNS(ns, 'circle');
      const fraction = (bounds.max - value) / (bounds.max - bounds.min || 1);
      circle.setAttribute('cx', String(width / 2));
      circle.setAttribute(
        'cy',
        String(margin.top + fraction * plotHeight),
      );
      circle.setAttribute('r', '4');
      circle.setAttribute('class', className);
      chart.append(circle);
    };
    point(real[0], 'series-real');
    if (hasImaginary) point(imaginary[0], 'series-imag');
  }
  byId('legend').replaceChildren();
  const labels = {
    n: [['n (real)', 'real'], ['k (imaginary)', 'imaginary']],
    e: [['ε₁ (real)', 'real'], ['ε₂ (imaginary)', 'imaginary']],
    k: [['k', 'real']],
    n2: [['n₂', 'real']],
  };
  for (const [label, className] of labels[parameter]) {
    const item = document.createElement('span');
    item.className = className;
    item.textContent = label;
    byId('legend').append(item);
  }
}

async function plotSpectrum() {
  if (!state.selected) return;
  const start = Number(byId('range-start').value);
  const end = Number(byId('range-end').value);
  const count = Number(byId('sample-count').value);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start <= 0 || end <= start) {
    showStatus('Enter a positive wavelength range with end greater than start.', true);
    return;
  }
  if (!Number.isInteger(count) || count < 2 || count > 1000) {
    showStatus('Sample count must be an integer from 2 through 1000.', true);
    return;
  }
  const revision = revisionSelect.value ? Number(revisionSelect.value) : null;
  const singlePoint = state.selectedRecord?.model === 'tabulated'
    && state.selectedRecord.data.f.length === 1;
  const unit = singlePoint ? state.selectedRecord.data.unit : 'nm';
  const coordinates = singlePoint
    ? [state.selectedRecord.data.f[0]]
    : Array.from(
      { length: count },
      (_, index) => start + (end - start) * index / (count - 1),
    );
  const request = {
    record_id: state.selected.id,
    revision,
    coordinates,
    unit,
    parameter: byId('parameter').value,
    interpolation: byId('interpolation').value,
  };
  showStatus('Evaluating optical model…');
  try {
    const result = await api('/api/v1/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    const real = result.values.map((value) => value.real);
    const imaginary = result.values.map((value) => value.imag);
    drawSpectrum(
      real,
      imaginary,
      result.coordinates,
      request.parameter,
      singlePoint ? `Source coordinate (${unit})` : 'Wavelength (nm)',
    );
    const rangeDescription = singlePoint
      ? `one source point at ${coordinates[0]} ${unit}`
      : `${count} points from ${start} to ${end} nm`;
    showStatus(`${state.selected.material_name} / ${state.selected.name}: ${rangeDescription}${revision ? ` · revision ${revision}` : ''}.`);
  } catch (error) {
    showStatus(error.message, true);
  }
}

function showPanelStatus(element, message, failed = false) {
  element.textContent = message;
  element.classList.toggle('error', failed);
}

function parseTabulatedText(text) {
  const rows = text.split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'));
  if (!rows.length) throw new Error('Enter or choose a data file first.');

  const coordinates = [];
  const real = [];
  const imaginary = [];
  for (const [index, line] of rows.entries()) {
    const columns = line.split(/[;,\t ]+/).filter(Boolean);
    if (index === 0 && columns.length === 3
        && /^(x|f|lambda|wavelength|coordinate|frequency)$/i.test(columns[0])
        && columns.slice(1).every((column) => !Number.isFinite(Number(column)))) {
      continue;
    }
    if (columns.length !== 3) {
      throw new Error(`Line ${index + 1} must contain exactly three columns.`);
    }
    const values = columns.map((column) => Number(column));
    if (columns.some((column) => column.trim() === '')
        || values.some((value) => !Number.isFinite(value))) {
      throw new Error(`Line ${index + 1} contains a non-finite numeric value.`);
    }
    coordinates.push(values[0]);
    real.push(values[1]);
    imaginary.push(values[2]);
  }
  if (coordinates.length < 2) {
    throw new Error('At least two data rows are required.');
  }
  return { coordinates, real, imaginary };
}

function buildUploadPreview(text, fileName = null, fileCount = 1) {
  const newMaterial = byId('upload-destination').value === 'new';
  const materialId = newMaterial
    ? byId('upload-material-id').value.trim()
    : byId('upload-material').value;
  const materialName = newMaterial ? byId('upload-material-name').value.trim() : null;
  const enteredName = byId('upload-name').value.trim();
  const fileStem = fileName ? fileName.replace(/\.[^.]+$/, '').trim() : '';
  const name = fileName
    ? fileCount > 1 && enteredName
      ? `${enteredName} - ${fileStem}`
      : enteredName || fileStem
    : enteredName;
  const kind = byId('upload-kind').value;
  const unit = byId('upload-unit').value;
  if (!materialId) throw new Error(newMaterial ? 'Enter a new material ID.' : 'Choose a material.');
  if (newMaterial && (!materialName || ['.', '..'].includes(materialId)
      || /[/\\]/.test(materialId))) {
    throw new Error('Enter a display name and a material ID without path separators.');
  }
  if (!name) throw new Error('Enter a record name.');
  text = text.trim();
  if (!text) throw new Error('Choose a file or paste spectrum data.');

  let payload;
  if (text.startsWith('{')) {
    payload = JSON.parse(text);
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)
        || !payload.data || typeof payload.data !== 'object') {
      throw new Error('JSON must be a complete XMDM record with a data object.');
    }
    payload = structuredClone(payload);
    payload.data.unit = unit;
    payload.data.type = kind === 'nk' ? 'n' : 'e';
  } else {
    const parsed = parseTabulatedText(text);
    payload = {
      schema_version: '1',
      physics: 'optics',
      model: 'tabulated',
      name,
      data: {
        unit,
        type: kind === 'nk' ? 'n' : 'e',
        f: parsed.coordinates,
        re: parsed.real,
        im: parsed.imaginary,
      },
      metadata: {},
    };
  }
  if (payload.model !== 'tabulated' || payload.physics !== 'optics') {
    throw new Error('Uploads must be tabulated optical records.');
  }
  payload.name = name;
  payload.data.unit = unit;
  payload.data.type = kind === 'nk' ? 'n' : 'e';
  if (!Array.isArray(payload.data.f)
      || !Array.isArray(payload.data.re)
      || !Array.isArray(payload.data.im)
      || payload.data.f.length !== payload.data.re.length
      || payload.data.f.length !== payload.data.im.length) {
    throw new Error('JSON data must contain matching f, re, and im arrays.');
  }
  if (!payload.metadata || typeof payload.metadata !== 'object'
      || Array.isArray(payload.metadata)) {
    throw new Error('JSON metadata must be an object.');
  }
  for (const [field, metadataKey] of [
    ['upload-author', 'author'],
    ['upload-source', 'source'],
    ['upload-description', 'description'],
  ]) {
    const value = byId(field).value.trim();
    if (value) payload.metadata[metadataKey] = value;
  }
  return {
    sourceName: fileName,
    sourceText: text,
    materialId,
    materialName,
    payload,
    coordinates: payload.data.f,
    real: payload.data.re,
    imaginary: payload.data.im,
    kind,
    unit,
  };
}

function invalidateUploadPreview() {
  state.uploadPreview = null;
  byId('submit-upload').disabled = true;
  showPanelStatus(byId('upload-status'), 'Changes made. Preview the spectrum before submitting.');
}

async function previewUpload() {
  try {
    const records = state.uploadFiles.length
      ? state.uploadFiles.map((file) => buildUploadPreview(
        file.text, file.name, state.uploadFiles.length,
      ))
      : [buildUploadPreview(byId('upload-data').value)];
    if (new Set(records.map((record) => record.payload.name)).size
        !== records.length) {
      throw new Error('Each selected file must produce a unique record name.');
    }
    state.uploadPreview = { records };
    byId('upload-file-choice-label').hidden = records.length < 2;
    const preview = records[Number(byId('upload-file-choice').value) || 0]
      || records[0];
    drawUploadPreview(preview);
    byId('submit-upload').disabled = false;
    const countLabel = records.length === 1
      ? ''
      : ` · ${records.length} files will be submitted`;
    showPanelStatus(
      byId('upload-status'),
      `Preview ready: ${preview.coordinates.length} points · ${preview.kind} · ${preview.unit}${countLabel}. Server verification runs when submitted.`,
    );
  } catch (error) {
    state.uploadPreview = null;
    byId('submit-upload').disabled = true;
    showPanelStatus(byId('upload-status'), error.message, true);
  }
}

function drawUploadPreview(preview) {
  drawSpectrum(
    preview.real,
    preview.imaginary,
    preview.coordinates,
    preview.kind === 'nk' ? 'n' : 'e',
    `Coordinate (${preview.unit})`,
  );
}

async function submitUpload() {
  if (!state.uploadPreview?.records.length) return;
  const token = byId('upload-token').value.trim();
  if (!token) {
    showPanelStatus(byId('upload-status'), 'Enter a records:write token.', true);
    return;
  }
  byId('submit-upload').disabled = true;
  const records = state.uploadPreview.records;
  const results = [];
  let submitted = 0;
  try {
    for (const record of records) {
      const result = await api('/api/v1/submissions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          material_id: record.materialId,
          ...(record.materialName === null ? {} : { material_name: record.materialName }),
          payload: record.payload,
        }),
      });
      results.push(result);
      submitted += 1;
    }
    showPanelStatus(
      byId('upload-status'),
      `${results.length} submission(s) passed verification and are pending administrator review.`,
    );
    state.uploadPreview = null;
    state.uploadFiles = [];
    byId('upload-file').value = '';
    byId('upload-file-choice-label').hidden = true;
    byId('upload-data').value = '';
    byId('submit-upload').disabled = true;
  } catch (error) {
    if (submitted) {
      state.uploadPreview.records = records.slice(submitted);
      state.uploadFiles = state.uploadPreview.records.map((record) => ({
        name: record.sourceName,
        text: record.sourceText,
      }));
      byId('upload-file').value = '';
      const choice = byId('upload-file-choice');
      choice.replaceChildren(...state.uploadPreview.records.map((record, index) =>
        new Option(record.payload.name, String(index)),
      ));
      choice.value = '0';
      showPanelStatus(
        byId('upload-status'),
        `${submitted} submission(s) were staged; the remaining ${state.uploadPreview.records.length} were not. ${error.message}`,
        true,
      );
    } else {
      showPanelStatus(byId('upload-status'), error.message, true);
    }
    byId('submit-upload').disabled = false;
  }
}

function submissionCard(submission) {
  const card = document.createElement('article');
  card.className = 'submission-card';
  const title = document.createElement('strong');
  title.textContent = `${submission.material_name} / ${submission.payload.name}`;
  const metadata = document.createElement('p');
  metadata.textContent = [
    ...(submission.new_material ? ['New material (created upon approval)'] : []),
    `${submission.payload.data.f.length} points`,
    `${submission.payload.data.type} · ${submission.payload.data.unit}`,
    `submitted by ${submission.submitter_name}`,
    new Date(submission.submitted_at).toLocaleString(),
  ].join(' · ');
  const description = document.createElement('p');
  description.textContent = submission.payload.metadata?.description || 'No description supplied.';
  const details = document.createElement('details');
  const summary = document.createElement('summary');
  summary.textContent = 'Show submitted data';
  const payload = document.createElement('pre');
  payload.textContent = JSON.stringify(submission.payload, null, 2);
  details.append(summary, payload);
  const buttons = document.createElement('div');
  buttons.className = 'submission-actions';
  for (const [decision, label] of submission.status === 'pending'
    ? [['approve', 'Approve'], ['reject', 'Reject']]
    : []) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    if (decision === 'reject') button.className = 'secondary-button';
    button.addEventListener('click', () => reviewSubmission(submission, decision));
    buttons.append(button);
  }
  card.append(title, metadata, description, details);
  if (buttons.childElementCount) card.append(buttons);
  return card;
}

function renderSubmissions() {
  const query = byId('submission-search').value.trim().toLocaleLowerCase();
  const visible = state.submissions.filter((submission) =>
    !query || JSON.stringify(submission).toLocaleLowerCase().includes(query));
  const list = byId('submission-list');
  list.replaceChildren(...visible.map(submissionCard));
  showPanelStatus(
    byId('admin-status'),
    visible.length
      ? `${visible.length} submission(s) shown.`
      : 'No submissions match this search.',
  );
}

async function loadSubmissions() {
  const token = byId('admin-token').value.trim();
  const list = byId('submission-list');
  list.replaceChildren();
  state.submissions = [];
  if (!token) {
    showPanelStatus(byId('admin-status'), 'Enter a tokens:admin token.', true);
    return;
  }
  try {
    const submissionStatus = byId('submission-status').value;
    const result = await api(
      `/api/v1/admin/submissions?status=${encodeURIComponent(submissionStatus)}&limit=1000`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    state.submissions = result.items;
    renderSubmissions();
  } catch (error) {
    showPanelStatus(byId('admin-status'), error.message, true);
  }
}

async function reviewSubmission(submission, decision) {
  const token = byId('admin-token').value.trim();
  const note = byId('review-note').value.trim();
  try {
    const result = await api(
      `/api/v1/admin/submissions/${encodeURIComponent(submission.submission_id)}/${decision}`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ note: note || null }),
      },
    );
    const message = result.status === 'accepted'
      ? `Approved and published as record ${result.record_id}, revision ${result.revision}.`
      : `Submission rejected${note ? `: ${note}` : '.'}`;
    await loadSubmissions();
    if (result.status === 'accepted') await loadAdminRecords();
    showPanelStatus(byId('admin-status'), message);
  } catch (error) {
    showPanelStatus(byId('admin-status'), error.message, true);
  }
}

function adminRecordCard(record) {
  const card = document.createElement('article');
  card.className = 'submission-card';
  const title = document.createElement('strong');
  title.textContent = `${record.material_name} / ${record.name}`;
  const metadata = document.createElement('p');
  metadata.textContent = [
    `${record.model} · ${record.physics}`,
    record.source || 'Source not specified',
    `revision ${record.revision}`,
    record.deleted_at
      ? `Archived ${new Date(record.deleted_at).toLocaleString()}`
      : 'Published',
  ].join(' · ');
  const action = document.createElement('button');
  action.type = 'button';
  action.textContent = record.deleted_at ? 'Restore record' : 'Archive record';
  if (record.deleted_at) {
    action.addEventListener('click', () => changeRecordState(record, 'restore'));
  } else {
    action.className = 'secondary-button';
    action.addEventListener('click', () => changeRecordState(record, 'archive'));
  }
  const actions = document.createElement('div');
  actions.className = 'submission-actions';
  actions.append(action);
  card.append(title, metadata, actions);
  return card;
}

async function loadAdminRecords() {
  const token = byId('admin-token').value.trim();
  const list = byId('admin-record-list');
  list.replaceChildren();
  if (!token) {
    showPanelStatus(byId('admin-record-status'), 'Enter a tokens:admin token.', true);
    return;
  }
  try {
    const query = byId('admin-record-search').value.trim();
    const result = await api(
      `/api/v1/admin/records?limit=1000&query=${encodeURIComponent(query)}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    list.replaceChildren(...result.items.map(adminRecordCard));
    showPanelStatus(
      byId('admin-record-status'),
      `${result.items.length} record(s) found, including archived records.`,
    );
  } catch (error) {
    showPanelStatus(byId('admin-record-status'), error.message, true);
  }
}

async function changeRecordState(record, action) {
  const token = byId('admin-token').value.trim();
  if (action === 'archive' && !window.confirm(
    `Archive ${record.material_name} / ${record.name}? Its history will be retained.`,
  )) return;
  try {
    const url = `/api/v1/admin/records/${encodeURIComponent(record.id)}`
      + (action === 'restore' ? '/restore' : '');
    await api(url, {
      method: action === 'restore' ? 'POST' : 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });
    await loadAdminRecords();
  } catch (error) {
    showPanelStatus(byId('admin-record-status'), error.message, true);
  }
}

async function refresh(updateMaterials = false) {
  const searchVersion = ++state.searchVersion;
  showStatus('Searching catalog…');
  try {
    if (updateMaterials) {
      await loadMaterials(byId('search').value.trim(), searchVersion);
      if (searchVersion !== state.searchVersion) return;
    }
    await loadRecords(searchVersion);
    if (searchVersion !== state.searchVersion) return;
    showStatus(`${state.records.length.toLocaleString()} matching records.`);
  } catch (error) {
    if (searchVersion === state.searchVersion) showStatus(error.message, true);
  }
}

if (byId('search')) {
byId('search').addEventListener('input', () => {
  window.clearTimeout(window.searchTimer);
  state.searchVersion += 1;
  window.searchTimer = window.setTimeout(() => refresh(true), 180);
});
materialSelect.addEventListener('change', () => refresh());
recordSelect.addEventListener('change', () => selectRecord().catch((error) => showStatus(error.message, true)));
revisionSelect.addEventListener('change', plotSpectrum);
byId('plot-button').addEventListener('click', plotSpectrum);
byId('parameter').addEventListener('change', plotSpectrum);
byId('interpolation').addEventListener('change', plotSpectrum);
}
if (byId('preview-upload')) {
byId('upload-destination').addEventListener('change', () => {
  const newMaterial = byId('upload-destination').value === 'new';
  byId('upload-material').disabled = newMaterial;
  byId('new-material-id-label').hidden = !newMaterial;
  byId('new-material-name-label').hidden = !newMaterial;
  invalidateUploadPreview();
});
byId('preview-upload').addEventListener('click', previewUpload);
byId('submit-upload').addEventListener('click', submitUpload);
byId('upload-file-choice').addEventListener('change', () => {
  if (!state.uploadPreview?.records.length) return;
  const preview = state.uploadPreview.records[
    Number(byId('upload-file-choice').value)
  ];
  if (preview) drawUploadPreview(preview);
});
byId('upload-file').addEventListener('change', async (event) => {
  const files = [...event.target.files];
  try {
    state.uploadFiles = await Promise.all(files.map(async (file) => ({
      name: file.name,
      text: await file.text(),
    })));
    byId('upload-data').value = '';
    const choice = byId('upload-file-choice');
    choice.replaceChildren(...state.uploadFiles.map((file, index) =>
      new Option(file.name, String(index)),
    ));
    byId('upload-file-choice-label').hidden = state.uploadFiles.length < 2;
    invalidateUploadPreview();
  } catch (error) {
    state.uploadFiles = [];
    showPanelStatus(byId('upload-status'), `Could not read file: ${error.message}`, true);
  }
});
for (const id of [
  'upload-material', 'upload-material-id', 'upload-material-name',
  'upload-name', 'upload-kind', 'upload-unit',
  'upload-author', 'upload-source', 'upload-description', 'upload-data',
]) {
  byId(id).addEventListener('input', invalidateUploadPreview);
  byId(id).addEventListener('change', invalidateUploadPreview);
}
byId('upload-data').addEventListener('input', () => {
  if (!byId('upload-data').value.trim()) return;
  state.uploadFiles = [];
  byId('upload-file').value = '';
  byId('upload-file-choice-label').hidden = true;
});
}
if (byId('refresh-submissions')) {
  byId('refresh-submissions').addEventListener('click', loadSubmissions);
  byId('submission-status').addEventListener('change', loadSubmissions);
  byId('submission-search').addEventListener('input', renderSubmissions);
  byId('search-admin-records').addEventListener('click', loadAdminRecords);
  byId('admin-record-search').addEventListener('keydown', (event) => {
    if (event.key === 'Enter') loadAdminRecords();
  });
}
if (byId('refresh-server-status')) {
  byId('refresh-server-status').addEventListener('click', refreshServerStatus);
}

async function refreshServerStatus() {
  const statusElement = byId('server-status');
  const details = byId('server-details');
  statusElement.textContent = 'Checking server health…';
  statusElement.classList.remove('error');
  details.replaceChildren();
  try {
    const [health, materials, records] = await Promise.all([
      api('/api/v1/health'),
      api('/api/v1/materials?limit=1'),
      api('/api/v1/records?limit=1'),
    ]);
    const rows = [
      ['Service', health.service],
      ['Health', health.status],
      ['Database', health.read_only ? 'Read-only JSON' : 'Writable SQLite'],
      ['Web interface', health.web_ui ? 'Enabled' : 'Disabled'],
      ['HTTP MCP', health.mcp_http ? 'Enabled at /mcp/' : 'Disabled'],
      ['Materials', materials.total.toLocaleString()],
      ['Published records', records.total.toLocaleString()],
    ];
    for (const [label, value] of rows) {
      const term = document.createElement('dt');
      term.textContent = label;
      const description = document.createElement('dd');
      description.textContent = value;
      details.append(term, description);
    }
    statusElement.textContent = 'Server is healthy.';
    byId('status-checked-at').textContent =
      `Last checked ${new Date().toLocaleString()}.`;
  } catch (error) {
    statusElement.textContent = error.message;
    statusElement.classList.add('error');
  }
}

async function start() {
  try {
    const page = document.body.dataset.page;
    if (page === 'data') {
      await loadMaterials();
      await refresh();
    } else if (page === 'upload') {
      await loadMaterials();
    } else if (page === 'status') {
      await refreshServerStatus();
    }
  } catch (error) {
    if (byId('status')) showStatus(error.message, true);
    if (byId('upload-status')) {
      showPanelStatus(byId('upload-status'), error.message, true);
    }
    if (byId('server-status')) {
      showPanelStatus(byId('server-status'), error.message, true);
    }
  }
}

start();
