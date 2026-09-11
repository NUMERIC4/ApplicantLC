// ApplicantLC — Main Frontend Controller

const state = {
  activeTab: 'tab-dashboard',
  dashboard: null,
  companies: [],
  applications: [],
  feedbacks: [],
  skills: [],
  documents: [],
  searchAlerts: [],
  candidate: null,
  aiConfig: null,
  pendingFitResult: null,
  pendingFeedbackResult: null,
  jobIngestionPreview: null,
  jobIngestionSourceText: null,
  jobVersionSource: 'imported',
  jobPreviousId: null,
  jobSourceHash: null,
  existingJob: null,
  cvDocumentId: null,
  cvProfile: null,
  cvReprocessing: false,
  affindaComparing: false
};

// ================= INITIALIZATION =================
document.addEventListener('DOMContentLoaded', async () => {
  initTabs();
  initModals();
  initForms();
  await loadAllData();
});

async function loadAllData() {
  await fetchCandidateProfile();
  await Promise.all([
    fetchDashboard(),
    fetchCompanies(),
    fetchApplications(),
    fetchFeedbacks(),
    fetchSkills(),
    fetchDocuments(),
    fetchSearchAlerts(),
    fetchAiConfig()
  ]);
}

// ================= API CALLS =================
async function fetchDashboard() {
  try {
    const res = await fetch('/api/dashboard');
    if (res.ok) {
      state.dashboard = await res.json();
      renderDashboard();
    }
  } catch (err) {
    console.error('Failed to load dashboard', err);
  }
}

async function fetchCompanies() {
  try {
    const res = await fetch('/api/companies');
    if (res.ok) {
      state.companies = await res.json();
      renderCompaniesPool();
      populateCompanySelects();
    }
  } catch (err) {
    console.error('Failed to load companies', err);
  }
}

async function fetchApplications() {
  try {
    const res = await fetch('/api/applications');
    if (res.ok) {
      state.applications = await res.json();
      renderKanban();
      populateApplicationSelects();
    }
  } catch (err) {
    console.error('Failed to load applications', err);
  }
}

async function fetchFeedbacks() {
  try {
    const res = await fetch('/api/feedbacks');
    if (res.ok) {
      state.feedbacks = await res.json();
      renderFeedbacks();
    }
  } catch (err) {
    console.error('Failed to load feedbacks', err);
  }
}

async function fetchSkills() {
  try {
    const res = await fetch('/api/skills');
    if (res.ok) {
      state.skills = await res.json();
      renderSkills();
    }
  } catch (err) {
    console.error('Failed to load skills', err);
  }
}

async function fetchDocuments() {
  try {
    const query = state.candidate?.id ? `?candidate_id=${encodeURIComponent(state.candidate.id)}` : '';
    const res = await fetch(`/api/documents${query}`);
    if (res.ok) {
      state.documents = await res.json();
      renderDocuments();
    }
  } catch (err) {
    console.error('Failed to load documents', err);
  }
}

async function fetchSearchAlerts() {
  try {
    const res = await fetch('/api/search-alerts');
    if (res.ok) {
      state.searchAlerts = await res.json();
      renderSearchAlerts();
    }
  } catch (err) {
    console.error('Failed to load search alerts', err);
  }
}

async function fetchCandidateProfile() {
  try {
    const res = await fetch('/api/candidates/current');
    if (res.ok) {
      state.candidate = await res.json();
      renderCandidateProfile();
    }
  } catch (err) {
    console.error('Failed to load candidate', err);
  }
}

async function fetchAiConfig() {
  try {
    const res = await fetch('/api/ai/config');
    if (res.ok) {
      state.aiConfig = await res.json();
      renderAiConfig();
    }
  } catch (err) {
    console.error('Failed to load AI config', err);
  }
}

// ================= RENDERERS =================
function renderDashboard() {
  if (!state.dashboard) return;
  const { metrics, daily_batch, companies_table, pipeline_funnel, forecast_text } = state.dashboard;

  // KPIs
  document.getElementById('kpiCompaniesPool').textContent = metrics.companies_pool;
  document.getElementById('kpiTotalApps').textContent = metrics.applications_total;
  document.getElementById('kpiFollowUps').textContent = metrics.open_follow_ups;
  document.getElementById('kpiFeedbacks').textContent = metrics.feedback_received;
  document.getElementById('kpiInterviews').textContent = metrics.interviews;

  // Highlight follow-ups if due
  const followCard = document.getElementById('cardFollowUps');
  if (metrics.open_follow_ups > 0) {
    followCard.style.borderColor = 'rgba(245, 158, 11, 0.5)';
  } else {
    followCard.style.borderColor = 'var(--border-subtle)';
  }

  // Daily Sprint Card
  document.getElementById('sprintDayBadge').textContent = `DAY ${daily_batch.day_no}`;
  document.getElementById('sprintFocus').textContent = daily_batch.focus || 'Focus Pool';
  document.getElementById('sprintStatusTag').textContent = daily_batch.status || 'in progress';
  document.getElementById('sprintNextPool').textContent = `Next Pool: ${daily_batch.next_pool || 'General Pipeline'}`;

  document.getElementById('sprintAppCount').textContent = `${daily_batch.actual_application} / ${daily_batch.target_application} Target`;
  const appPct = Math.min(100, Math.round((daily_batch.actual_application / (daily_batch.target_application || 1)) * 100));
  document.getElementById('sprintAppProgress').style.width = `${appPct}%`;

  document.getElementById('sprintEvalCount').textContent = `${daily_batch.actual_evaluation} / ${daily_batch.target_evaluation} Target`;
  const evalPct = Math.min(100, Math.round((daily_batch.actual_evaluation / (daily_batch.target_evaluation || 1)) * 100));
  document.getElementById('sprintEvalProgress').style.width = `${evalPct}%`;

  // Today's Companies Table
  const tbody = document.getElementById('todayCompaniesTableBody');
  tbody.innerHTML = '';
  if (!companies_table || companies_table.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-muted" style="text-align:center; padding:1.5rem;">No companies in today's batch yet. Add some to begin.</td></tr>`;
  } else {
    companies_table.forEach(c => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td><strong>${escapeHtml(c.name)}</strong><br><small class="text-muted">${escapeHtml(c.city || 'Remote')}</small></td>
        <td><span class="badge-class class-${formatClassClass(c.class)}">${escapeHtml(c.class)}</span></td>
        <td><span class="badge-effort effort-${formatEffortClass(c.effort)}">${escapeHtml(c.effort)}</span></td>
        <td>${escapeHtml(c.technical_field || 'Tech')}</td>
        <td><span class="badge-status">${escapeHtml(c.status || 'Evaluating')}</span></td>
        <td>
          <button type="button" class="btn btn-sm btn-outline js-fit">AI Fit</button>
          <button type="button" class="btn btn-sm btn-primary js-apply">+ Apply</button>
        </td>
      `;
      tr.querySelector('.js-fit').addEventListener('click', () => openFitEvaluatorForCompany(c.name, c.technical_field || ''));
      tr.querySelector('.js-apply').addEventListener('click', () => quickApplyToCompany(c.id));
      tbody.appendChild(tr);
    });
  }

  // Funnel & Forecast
  if (pipeline_funnel) {
    const total = Math.max(1, metrics.applications_total);
    const setFunnel = (id, numId, count) => {
      document.getElementById(numId).textContent = count;
      const pct = Math.min(100, Math.max(15, Math.round((count / total) * 100)));
      document.getElementById(id).style.width = `${pct}%`;
    };
    setFunnel('funnelPreparing', 'funnelNumPreparing', pipeline_funnel['Preparing'] || 0);
    setFunnel('funnelApplied', 'funnelNumApplied', pipeline_funnel['Applied'] || 0);
    setFunnel('funnelInterview', 'funnelNumInterview', pipeline_funnel['Interview'] || 0);
    setFunnel('funnelFeedback', 'funnelNumFeedback', metrics.feedback_received || 0);
  }
}

function renderKanban() {
  const stages = [
    { key: 'Preparing', colId: 'col-Preparing', countId: 'count-Preparing' },
    { key: 'Portal submitted', colId: 'col-Submitted', countId: 'count-Submitted' },
    { key: 'Recruiter review', colId: 'col-Recruiter', countId: 'count-Recruiter' },
    { key: 'functional department review', colId: 'col-Functional', countId: 'count-Functional' },
    { key: 'Interview', colId: 'col-Interview', countId: 'count-Interview' },
    { key: 'Offer', colId: 'col-Offer', countId: 'count-Offer' },
    { key: 'Rejected', colId: 'col-Rejected', countId: 'count-Rejected' }
  ];

  stages.forEach(s => {
    const col = document.getElementById(s.colId);
    if (col) col.innerHTML = '';
  });

  const counts = { 'Preparing': 0, 'Portal submitted': 0, 'Recruiter review': 0, 'functional department review': 0, 'Interview': 0, 'Offer': 0, 'Rejected': 0 };

  state.applications.forEach(app => {
    const stage = app.current_stage || 'Portal submitted';
    if (counts[stage] !== undefined) counts[stage]++;

    let targetColId = 'col-Submitted';
    if (stage === 'Preparing') targetColId = 'col-Preparing';
    else if (stage === 'Portal submitted') targetColId = 'col-Submitted';
    else if (stage === 'Recruiter review') targetColId = 'col-Recruiter';
    else if (stage === 'functional department review') targetColId = 'col-Functional';
    else if (stage === 'Interview') targetColId = 'col-Interview';
    else if (stage === 'Offer') targetColId = 'col-Offer';
    else if (stage === 'Rejected') targetColId = 'col-Rejected';

    const col = document.getElementById(targetColId);
    if (col) {
      const card = document.createElement('div');
      card.className = 'app-card';
      const compName = app.company ? app.company.name : 'Target Company';
      const followUpBadge = app.follow_up_date ? `<span class="pill-item">Follow-up: ${app.follow_up_date}</span>` : '';

      card.innerHTML = `
        <div class="app-card-header">
          <span class="app-comp-name">${escapeHtml(compName)}</span>
          <span class="badge-class class-${formatClassClass(app.company_class || 'B')}">${escapeHtml(app.company_class || 'B')}</span>
        </div>
        <div class="app-job-title">${escapeHtml(app.job_title)}</div>
        <div class="app-card-meta">
          <span>${escapeHtml(app.application_channel || 'Direct')}</span>
          ${followUpBadge}
        </div>
        <select class="app-stage-select js-stage-select">
          <option value="Preparing" ${stage === 'Preparing' ? 'selected' : ''}>Stage: Preparing</option>
          <option value="Portal submitted" ${stage === 'Portal submitted' ? 'selected' : ''}>Stage: Submitted</option>
          <option value="Recruiter review" ${stage === 'Recruiter review' ? 'selected' : ''}>Stage: Recruiter Review</option>
          <option value="functional department review" ${stage === 'functional department review' ? 'selected' : ''}>Stage: Functional Review</option>
          <option value="Interview" ${stage === 'Interview' ? 'selected' : ''}>Stage: Interview</option>
          <option value="Offer" ${stage === 'Offer' ? 'selected' : ''}>Stage: Offer 🎉</option>
          <option value="Rejected" ${stage === 'Rejected' ? 'selected' : ''}>Stage: Rejection / Feedback</option>
        </select>
      `;
      card.querySelector('.js-stage-select').addEventListener('change', (event) => updateApplicationStage(app.id, event.target.value));
      col.appendChild(card);
    }
  });

  stages.forEach(s => {
    const el = document.getElementById(s.countId);
    if (el) el.textContent = counts[s.key] || 0;
  });
}

function renderCompaniesPool() {
  const tbody = document.getElementById('companiesPoolTableBody');
  tbody.innerHTML = '';
  if (!state.companies || state.companies.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 2rem;">No companies added yet.</td></tr>`;
    return;
  }

  state.companies.forEach(c => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${escapeHtml(c.name)}</strong></td>
      <td>${escapeHtml(c.city || '—')}, ${escapeHtml(c.region || '')}</td>
      <td><span class="badge-class class-${formatClassClass(c.class_grade)}">${escapeHtml(c.class_grade || 'B')}</span></td>
      <td><span class="badge-effort effort-${formatEffortClass(c.recommended_effort)}">${escapeHtml(c.recommended_effort || 'Medium')}</span></td>
      <td>${escapeHtml(c.technical_field || 'General Tech')}</td>
      <td>${escapeHtml(c.company_eligibility || 'yes')}</td>
      <td><span class="badge-status">${escapeHtml(c.research_status || 'Evaluating')}</span></td>
      <td>
        <button type="button" class="btn btn-sm btn-outline js-fit">AI Fit</button>
        <button type="button" class="btn btn-sm btn-primary js-apply">+ Apply</button>
      </td>
    `;
    tr.querySelector('.js-fit').addEventListener('click', () => openFitEvaluatorForCompany(c.name, c.technical_field || ''));
    tr.querySelector('.js-apply').addEventListener('click', () => quickApplyToCompany(c.id));
    tbody.appendChild(tr);
  });
}

function renderFeedbacks() {
  const container = document.getElementById('feedbackListContainer');
  container.innerHTML = '';
  if (!state.feedbacks || state.feedbacks.length === 0) {
    container.innerHTML = `<p class="text-muted" style="padding:1rem;">No feedback logged yet. When receiving a response or rejection, use the AI Analyzer to extract actionable skill gaps!</p>`;
    return;
  }

  state.feedbacks.forEach(fb => {
    const card = document.createElement('div');
    card.className = 'feedback-card';
    card.innerHTML = `
      <div class="fb-meta-row">
        <div>
          <strong>Feedback #${fb.id}</strong> • <small class="text-muted">${fb.feedback_date || 'Recent'}</small>
        </div>
        <span class="fb-type-tag">${escapeHtml(fb.feedback_type || 'Unknown')}</span>
      </div>
      <div class="fb-raw-quote">"${escapeHtml(fb.raw_feedback || 'No raw text recorded')}"</div>
      <div class="fb-action-row">
        <strong>Identified Gaps:</strong> ${escapeHtml(fb.skill_gap || 'None specified')}<br>
        ${fb.action_taken ? `<strong>Action Taken:</strong> ${escapeHtml(fb.action_taken)}` : ''}
      </div>
    `;
    container.appendChild(card);
  });
}

function renderSkills() {
  const grid = document.getElementById('skillsGridContainer');
  grid.innerHTML = '';
  if (!state.skills || state.skills.length === 0) {
    grid.innerHTML = `<p class="text-muted" style="padding:1rem;">No skills logged in matrix.</p>`;
    return;
  }

  state.skills.forEach(s => {
    const card = document.createElement('div');
    card.className = 'skill-card';
    card.innerHTML = `
      <div class="skill-header">
        <span class="skill-name">${escapeHtml(s.name)}</span>
        <span class="skill-level-badge level-${formatLevelClass(s.current_level)}">${escapeHtml(s.current_level || 'Intermediate')}</span>
      </div>
      <div class="skill-evidence">${escapeHtml(s.evidence_source || 'Coursework / Personal project')}</div>
    `;
    grid.appendChild(card);
  });
}

function renderDocuments() {
  const tbody = document.getElementById('documentsTableBody');
  tbody.innerHTML = '';
  if (!state.documents || state.documents.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:1.5rem;">No documents uploaded yet.</td></tr>`;
    return;
  }

  state.documents.forEach(d => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${escapeHtml(d.name)}</strong></td>
      <td><span class="pill-item">${escapeHtml(d.doc_type || 'CV')}</span></td>
      <td>${d.version_date || '—'}</td>
      <td><span class="badge-status">${escapeHtml(d.confirmation_status === 'unconfirmed' ? 'Review Required' : d.status || 'active')}</span>${d.parser_version ? `<small> · ${escapeHtml(d.parser_version)}</small>` : ''}</td>
      <td>${escapeHtml(d.owner_note || '—')}</td>
      <td>${d.can_open_file ? '<button type="button" class="btn btn-sm btn-outline js-open-document">Open File</button>' : '<span class="text-muted">No file available</span>'}</td>
      <td>${d.doc_type === 'CV' ? '<button type="button" class="btn btn-sm btn-outline js-open-cv">Open Review</button> ' : ''}${d.can_reprocess ? '<button type="button" class="btn btn-sm btn-outline js-reprocess-cv">Reprocess</button> ' : ''}${d.can_compare_affinda ? '<button type="button" class="btn btn-sm btn-outline js-compare-affinda">Compare with Affinda</button> ' : ''}<button type="button" class="btn btn-sm btn-outline js-delete-document">Delete</button></td>
    `;
    tr.querySelector('.js-open-document')?.addEventListener('click', () => openDocumentFile(d.id));
    tr.querySelector('.js-open-cv')?.addEventListener('click', () => openCvReview(d.id));
    tr.querySelector('.js-reprocess-cv')?.addEventListener('click', () => startCvReprocess(d.id));
    tr.querySelector('.js-compare-affinda')?.addEventListener('click', () => startAffindaComparison(d.id));
    tr.querySelector('.js-delete-document').addEventListener('click', () => deleteDocument(d.id));
    tbody.appendChild(tr);
  });
}

function renderSearchAlerts() {
  const tbody = document.getElementById('searchAlertsTableBody');
  tbody.innerHTML = '';
  if (!state.searchAlerts || state.searchAlerts.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:1.5rem;">No search alerts registered.</td></tr>`;
    return;
  }

  state.searchAlerts.forEach(a => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><strong>${escapeHtml(a.filter_name)}</strong></td>
      <td><span class="pill-item">${escapeHtml(a.platform || 'LinkedIn')}</span></td>
      <td><code>${escapeHtml(a.keywords || '—')}</code></td>
      <td>${escapeHtml(a.join_as || 'Internship')}</td>
      <td><span class="badge-status">${escapeHtml(a.status || 'Active')}</span></td>
      <td>${a.last_checked || '—'}</td>
      <td>${escapeHtml(a.last_results || '—')}</td>
      <td><button type="button" class="btn btn-sm btn-outline js-delete-alert">Remove</button></td>
    `;
    tr.querySelector('.js-delete-alert').addEventListener('click', () => deleteSearchAlert(a.id));
    tbody.appendChild(tr);
  });
}

function renderCandidateProfile() {
  if (!state.candidate) return;
  const c = state.candidate;
  document.getElementById('headerCandName').textContent = c.profile_name;
  document.getElementById('headerCandTarget').textContent = `${c.uni || ''} • ${c.target || ''}`;

  document.getElementById('candProfileName').value = c.profile_name || '';
  document.getElementById('candDegree').value = c.degree || '';
  document.getElementById('candUni').value = c.uni || '';
  document.getElementById('candTarget').value = c.target || '';
  document.getElementById('candAvailability').value = c.availability || '';
  document.getElementById('candLocation').value = c.location || '';
  document.getElementById('candNotes').value = c.notes || '';
}

function renderAiConfig() {
  if (!state.aiConfig) return;
  const cfg = state.aiConfig;
  document.getElementById('headerModelLabel').textContent = `NVIDIA NIM: ${cfg.model}`;
  document.getElementById('selectNvidiaModel').value = cfg.model_name;
  document.getElementById('inputNvidiaBaseUrl').value = cfg.base_url;
  document.getElementById('nvidiaConfigStatus').textContent = cfg.api_key_present
    ? 'Configured on the backend'
    : 'Not configured — set NVIDIA_API_KEY in the backend .env file';
}

function populateCompanySelects() {
  const sel = document.getElementById('appCompanySelect');
  if (!sel) return;
  sel.innerHTML = '<option value="">Select Target Company...</option>';
  state.companies.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.id;
    opt.textContent = `${c.name} (Class ${c.class_grade || 'B'})`;
    sel.appendChild(opt);
  });
}

function populateApplicationSelects() {
  const sel = document.getElementById('fbAppSelect');
  if (!sel) return;
  sel.innerHTML = '<option value="">Select Application...</option>';
  state.applications.forEach(a => {
    const opt = document.createElement('option');
    opt.value = a.id;
    const compName = a.company ? a.company.name : 'Target';
    opt.textContent = `#${a.id} — ${compName}: ${a.job_title} (${a.current_stage || a.status})`;
    sel.appendChild(opt);
  });
}

// ================= TABS =================
function initTabs() {
  const tabs = document.querySelectorAll('.nav-tab');
  tabs.forEach(t => {
    t.addEventListener('click', () => {
      tabs.forEach(item => item.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      t.classList.add('active');
      const paneId = t.getAttribute('data-tab');
      const targetPane = document.getElementById(paneId);
      if (targetPane) targetPane.classList.add('active');
      state.activeTab = paneId;
    });
  });
}

// ================= MODALS =================
function initModals() {
  // Close buttons
  document.querySelectorAll('[data-close]').forEach(btn => {
    btn.addEventListener('click', () => {
      const modalId = btn.getAttribute('data-close');
      const modal = document.getElementById(modalId);
      if (modal) modal.classList.remove('active');
    });
  });

  // Open Fit Evaluator
  document.getElementById('btnOpenFitEvaluator')?.addEventListener('click', () => {
    openModal('modalFitEvaluator');
  });

  // Open New Application
  document.getElementById('btnNewApplication')?.addEventListener('click', () => {
    openModal('modalNewApplication');
  });
  document.getElementById('btnNewApplicationFromKanban')?.addEventListener('click', () => {
    openModal('modalNewApplication');
  });

  document.getElementById('btnImportJobUrl')?.addEventListener('click', () => {
    openModal('modalJobIngestion');
  });
  document.getElementById('btnAddDocumentModal')?.addEventListener('click', () => openModal('modalCvIngestion'));

  // Open Log Feedback
  document.getElementById('btnLogFeedback')?.addEventListener('click', () => {
    openModal('modalFeedbackAnalyzer');
  });
  document.getElementById('btnParseRejectionModal')?.addEventListener('click', () => {
    openModal('modalFeedbackAnalyzer');
  });

  // Open New Company
  document.getElementById('btnCreateCompanyModal')?.addEventListener('click', () => {
    openModal('modalNewCompany');
  });
  document.getElementById('btnQuickAddCompany')?.addEventListener('click', () => {
    openModal('modalNewCompany');
  });

  // Edit Sprint
  document.getElementById('btnAdvanceSprint')?.addEventListener('click', () => {
    if (state.dashboard && state.dashboard.daily_batch) {
      const b = state.dashboard.daily_batch;
      document.getElementById('sprintInputDayNo').value = b.day_no;
      document.getElementById('sprintInputTargetApp').value = b.target_application;
      document.getElementById('sprintInputTargetEval').value = b.target_evaluation;
      document.getElementById('sprintInputFocus').value = b.focus;
      document.getElementById('sprintInputNextPool').value = b.next_pool;
      document.getElementById('sprintInputStatus').value = b.status;
    }
    openModal('modalSprint');
  });
}

function openModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.add('active');
}

function closeModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.remove('active');
}

// ================= FORMS & ACTIONS =================
function initForms() {
  document.getElementById('formCvUpload')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const file = document.getElementById('cvUploadFile').files[0];
    const feedback = document.getElementById('cvUploadFeedback');
    if (!file || !state.candidate?.id || state.cvReprocessing) return;
    const submitButton = event.submitter;
    const body = new FormData();
    body.append('candidate_id', state.candidate.id);
    body.append('file', file);
    setCvBusy(true);
    feedback.textContent = 'Processing CV with layout-aware parsing and NVIDIA analysis. This may take up to approximately two minutes...';
    try {
      const response = await fetch('/api/documents/cv/upload', { method: 'POST', body });
      const payload = await response.json();
      if (!response.ok) { feedback.textContent = payload.detail?.message || 'CV upload failed.'; return; }
      showCvReview(payload);
      document.getElementById('btnReprocessCv').style.display = payload.reprocess_available ? 'inline-block' : 'none';
      feedback.textContent = payload.state === 'duplicate' ? 'This exact CV already exists.' : payload.state === 'reused' ? 'A same-content CV profile was reused; please review it.' : 'Extraction complete. Review before confirmation.';
    } catch (_) { feedback.textContent = 'CV analysis could not be completed. Please try again later.'; }
    finally { setCvBusy(false); }
  });

  document.getElementById('btnReprocessCv')?.addEventListener('click', async (event) => {
    await startCvReprocess(state.cvDocumentId, event.currentTarget);
  });

  document.getElementById('btnConfirmCv')?.addEventListener('click', async () => {
    const feedback = document.getElementById('cvConfirmFeedback');
    let profile;
    try { profile = JSON.parse(document.getElementById('cvProfileJson').value); }
    catch (_) { feedback.textContent = 'The structured profile must be valid JSON.'; return; }
    const response = await fetch(`/api/documents/cv/${state.cvDocumentId}/confirm`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ candidate_id: state.candidate.id, profile }) });
    const payload = await response.json();
    if (!response.ok) { feedback.textContent = payload.detail?.message || 'CV confirmation failed.'; return; }
    feedback.textContent = 'Confirmed CV profile saved.';
    await fetchDocuments();
  });

  document.getElementById('formJobIngest')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const url = document.getElementById('jobIngestUrl').value.trim();
    const spinner = document.getElementById('jobExtractSpinner');
    const feedback = document.getElementById('jobIngestFeedback');
    const panel = document.getElementById('jobPreviewPanel');
    if (!url) return;

    spinner.style.display = 'inline-block';
    feedback.textContent = '';
    panel.style.display = 'none';
    try {
      const response = await fetch('/api/jobs/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail?.message || 'Job extraction failed.');
      }
      if (payload.state === 'duplicate') {
        state.existingJob = payload.latest_job;
        document.getElementById('jobDuplicateSummary').textContent = `${payload.latest_job.company_name} — ${payload.latest_job.title}, Version ${payload.latest_job.version_number}`;
        document.getElementById('jobDuplicatePanel').style.display = 'block';
        return;
      }
      beginJobPreview(payload, 'imported');
      feedback.textContent = 'Extraction complete. Review and correct every field before saving.';
      feedback.style.color = 'var(--accent-emerald)';
    } catch (error) {
      feedback.textContent = error.message || 'Job extraction failed.';
      feedback.style.color = 'var(--accent-rose)';
    } finally {
      spinner.style.display = 'none';
    }
  });

  document.getElementById('btnShowPasteJob')?.addEventListener('click', () => {
    document.getElementById('formJobPaste').style.display = 'block';
  });

  document.getElementById('formJobPaste')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const text = document.getElementById('jobPasteText').value;
    const response = await fetch('/api/jobs/extract-text', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
    const payload = await response.json();
    if (!response.ok) {
      document.getElementById('jobIngestFeedback').textContent = payload.detail?.message || 'Text extraction failed.';
      return;
    }
    beginJobPreview(payload, 'pasted_text');
    document.getElementById('jobIngestFeedback').textContent = payload.source_text_truncated ? 'Extraction complete; the pasted source was truncated for review.' : 'Extraction complete. Review before saving.';
  });

  document.getElementById('btnCancelJobDuplicate')?.addEventListener('click', () => {
    document.getElementById('jobDuplicatePanel').style.display = 'none';
  });

  document.getElementById('btnCheckJobUpdate')?.addEventListener('click', async () => {
    const response = await fetch('/api/jobs/check-update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: document.getElementById('jobIngestUrl').value.trim() }) });
    const payload = await response.json();
    if (!response.ok) {
      document.getElementById('jobIngestFeedback').textContent = payload.detail?.message || 'Update check failed.';
      return;
    }
    if (payload.state === 'unchanged') {
      document.getElementById('jobIngestFeedback').textContent = payload.message;
      return;
    }
    beginJobPreview(payload, 'source_update', payload.existing_job_id, payload.source_hash);
    document.getElementById('jobDuplicatePanel').style.display = 'none';
  });

  document.getElementById('btnOpenExistingJob')?.addEventListener('click', async () => {
    const response = await fetch(`/api/jobs/${state.existingJob.id}`);
    const payload = await response.json();
    if (!response.ok) return;
    state.existingJob = payload.job;
    state.jobIngestionPreview = { required_qualifications: payload.requirements.filter(item => item.importance === 'required').map(item => ({ text: item.requirement, category: item.category, importance: 'required', source_evidence: item.source_text })), preferred_qualifications: payload.requirements.filter(item => item.importance === 'preferred').map(item => ({ text: item.requirement, category: item.category, importance: 'preferred', source_evidence: item.source_text })) };
    state.jobIngestionSourceText = payload.job.raw_source_text;
    populateJobPreview({ company_name: payload.company.name, position_title: payload.job.title, location: payload.job.location, source_platform: payload.job.source_platform, job_description: payload.job.description, source_url: payload.job.source_url, ...state.jobIngestionPreview });
    setJobPreviewEditable(false);
    document.getElementById('jobPreviewPanel').style.display = 'block';
    document.getElementById('jobDuplicatePanel').style.display = 'none';
    document.getElementById('btnConfirmJob').style.display = 'none';
    document.getElementById('btnEditExistingJob').style.display = 'inline-block';
    document.getElementById('jobVersionLabel').textContent = `Version ${payload.job.version_number} — Source: ${payload.job.version_source}`;
  });

  document.getElementById('btnEditExistingJob')?.addEventListener('click', () => {
    state.jobVersionSource = 'manual_correction';
    state.jobPreviousId = state.existingJob.id;
    setJobPreviewEditable(true);
    document.getElementById('btnConfirmJob').style.display = 'inline-block';
    document.getElementById('btnConfirmJob').textContent = 'Save as New Version';
    document.getElementById('jobVersionLabel').textContent = 'Editing will create a new historical version — Source: Manual correction';
  });

  document.getElementById('btnConfirmJob')?.addEventListener('click', async () => {
    const feedback = document.getElementById('jobConfirmFeedback');
    const companyName = document.getElementById('jobPreviewCompany').value.trim();
    const positionTitle = document.getElementById('jobPreviewTitle').value.trim();
    const sourceUrl = document.getElementById('jobPreviewUrl').value.trim();
    if (!companyName || !positionTitle || (state.jobVersionSource !== 'pasted_text' && !sourceUrl)) {
      feedback.textContent = 'Company and position must be confirmed; URL is required for URL imports.';
      feedback.style.color = 'var(--accent-rose)';
      return;
    }
    try {
      const isManual = state.jobVersionSource === 'manual_correction';
      const response = await fetch(isManual ? `/api/jobs/${state.jobPreviousId}/manual-version` : '/api/jobs/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          company_name: companyName,
          position_title: positionTitle,
          source_url: sourceUrl || null,
          location: document.getElementById('jobPreviewLocation').value.trim() || null,
          source_platform: document.getElementById('jobPreviewPlatform').value.trim() || null,
          job_description: document.getElementById('jobPreviewDescription').value.trim() || null,
          source_text: state.jobIngestionSourceText,
          required_qualifications: reviewedRequirements('jobPreviewRequired', 'required'),
          preferred_qualifications: reviewedRequirements('jobPreviewPreferred', 'preferred'),
          ...(isManual ? {} : { version_source: state.jobVersionSource, supersedes_job_id: state.jobPreviousId, source_hash: state.jobSourceHash })
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail?.message || 'Saving the confirmed job failed.');
      }
      feedback.textContent = `Confirmed and saved: ${payload.job.title}`;
      feedback.style.color = 'var(--accent-emerald)';
      state.jobIngestionPreview = null;
      await fetchCompanies();
    } catch (error) {
      feedback.textContent = error.message || 'Saving the confirmed job failed.';
      feedback.style.color = 'var(--accent-rose)';
    }
  });

  // AI Fit Evaluator Trigger
  document.getElementById('btnRunAiFitEvaluation')?.addEventListener('click', async () => {
    const compName = document.getElementById('aiFitCompanyName').value.trim();
    const jobTitle = document.getElementById('aiFitJobTitle').value.trim();
    const techField = document.getElementById('aiFitTechField').value.trim();
    const jobDesc = document.getElementById('aiFitJobDesc').value.trim();

    if (!compName || !jobTitle) {
      alert('Please provide at least Company Name and Job Title.');
      return;
    }

    const spinner = document.getElementById('fitSpinner');
    spinner.style.display = 'inline-block';

    try {
      const res = await fetch('/api/ai/evaluate-fit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          company_name: compName,
          job_title: jobTitle,
          technical_field: techField,
          job_description: jobDesc
        })
      });

      if (res.ok) {
        const data = await res.json();
        state.pendingFitResult = { ...data, company_name: compName, job_title: jobTitle, technical_field: techField };
        renderFitResult(data);
      } else {
        alert('Fit evaluation failed.');
      }
    } catch (err) {
      console.error(err);
      alert('Network error while running fit evaluation.');
    } finally {
      spinner.style.display = 'none';
    }
  });

  // Save Company From Fit Result
  document.getElementById('btnSaveCompanyFromFit')?.addEventListener('click', async () => {
    if (!state.pendingFitResult) return;
    const r = state.pendingFitResult;
    try {
      const res = await fetch('/api/companies', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: r.company_name,
          technical_field: r.technical_field,
          class_grade: r.class_grade,
          recommended_effort: r.recommended_effort,
          evidence_confidence: r.evidence_confidence,
          company_eligibility: 'yes',
          research_status: 'Eligible',
          notes: r.rationale
        })
      });
      if (res.ok) {
        alert('Company saved to pool!');
        closeModal('modalFitEvaluator');
        await fetchCompanies();
        await fetchDashboard();
      }
    } catch (err) {
      console.error(err);
    }
  });

  // Create Application From Fit Result
  document.getElementById('btnCreateAppFromFit')?.addEventListener('click', async () => {
    if (!state.pendingFitResult) return;
    const r = state.pendingFitResult;
    // First find or create company
    let comp = state.companies.find(c => c.name.toLowerCase() === r.company_name.toLowerCase());
    let compId = comp ? comp.id : null;
    if (!compId) {
      const res = await fetch('/api/companies', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: r.company_name,
          technical_field: r.technical_field,
          class_grade: r.class_grade,
          recommended_effort: r.recommended_effort,
          notes: r.rationale
        })
      });
      if (res.ok) {
        const newC = await res.json();
        compId = newC.id;
      }
    }

    if (compId) {
      const appRes = await fetch('/api/applications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          company_id: compId,
          job_title: r.job_title,
          company_class: r.class_grade,
          company_recommended_effort: r.recommended_effort,
          status: 'Applied',
          current_stage: 'Portal submitted',
          notes: r.rationale
        })
      });
      if (appRes.ok) {
        alert('Application created and linked to sprint batch!');
        closeModal('modalFitEvaluator');
        await loadAllData();
      }
    }
  });

  // Feedback Analyzer Trigger
  document.getElementById('btnRunFeedbackAnalysis')?.addEventListener('click', async () => {
    const appId = document.getElementById('fbAppSelect').value;
    const stage = document.getElementById('fbStageSelect').value;
    const rawText = document.getElementById('fbRawText').value.trim();

    if (!appId || !rawText) {
      alert('Please select an application and paste the feedback message.');
      return;
    }

    const spinner = document.getElementById('fbSpinner');
    spinner.style.display = 'inline-block';

    try {
      const res = await fetch('/api/ai/extract-feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          application_id: parseInt(appId),
          stage: stage,
          raw_feedback_text: rawText
        })
      });

      if (res.ok) {
        const data = await res.json();
        state.pendingFeedbackResult = { ...data, application_id: parseInt(appId), raw_feedback_text: rawText, stage: stage };
        renderFeedbackResult(data);
      } else {
        alert('Feedback extraction failed.');
      }
    } catch (err) {
      console.error(err);
      alert('Network error while running feedback extraction.');
    } finally {
      spinner.style.display = 'none';
    }
  });

  // Copy Feedback Reply
  document.getElementById('btnCopyFeedbackReply')?.addEventListener('click', () => {
    const text = document.getElementById('fbDraftReply').value;
    navigator.clipboard.writeText(text);
    alert('Polite feedback reply copied to clipboard!');
  });

  // Save Feedback & Update Learning Curve
  document.getElementById('btnSaveFeedbackAndGaps')?.addEventListener('click', async () => {
    if (!state.pendingFeedbackResult) return;
    const p = state.pendingFeedbackResult;
    try {
      const res = await fetch('/api/feedbacks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          application_id: p.application_id,
          stage: p.stage,
          feedback_type: p.feedback_type,
          raw_feedback: p.raw_feedback_text,
          skill_gap: p.extracted_skill_gaps.join(', '),
          actionable: p.is_actionable,
          action_taken: p.action_plan_for_candidate,
          add_to_learning_curve: true
        })
      });

      if (res.ok) {
        alert('Feedback logged and learning curve updated with new skill gaps!');
        closeModal('modalFeedbackAnalyzer');
        await loadAllData();
      }
    } catch (err) {
      console.error(err);
    }
  });

  // Form: New Application
  document.getElementById('formNewApplication')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const companyId = parseInt(document.getElementById('appCompanySelect').value);
    const jobTitle = document.getElementById('appJobTitle').value.trim();
    const jobId = document.getElementById('appJobId').value.trim();
    const jobUrl = document.getElementById('appJobUrl').value.trim();
    const channel = document.getElementById('appChannel').value;
    const type = document.getElementById('appType').value;
    const status = document.getElementById('appStatus').value;
    const followUp = document.getElementById('appFollowUpDate').value || null;
    const notes = document.getElementById('appNotes').value.trim();

    try {
      const res = await fetch('/api/applications', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          company_id: companyId,
          job_title: jobTitle,
          job_id: jobId,
          job_url: jobUrl,
          application_channel: channel,
          application_type: type,
          status: status,
          current_stage: status === 'Applied' ? 'Portal submitted' : status,
          follow_up_date: followUp,
          notes: notes
        })
      });

      if (res.ok) {
        closeModal('modalNewApplication');
        e.target.reset();
        await loadAllData();
      }
    } catch (err) {
      console.error(err);
    }
  });

  // Form: New Company
  document.getElementById('formNewCompany')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('compName').value.trim();
    const city = document.getElementById('compCity').value.trim();
    const region = document.getElementById('compRegion').value.trim();
    const webpage = document.getElementById('compWebpage').value.trim();
    const techField = document.getElementById('compTechField').value.trim();
    const classGrade = document.getElementById('compClass').value;
    const effort = document.getElementById('compEffort').value;
    const eligibility = document.getElementById('compEligibility').value;
    const notes = document.getElementById('compNotes').value.trim();

    try {
      const res = await fetch('/api/companies', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name,
          city: city,
          region: region,
          webpage: webpage,
          technical_field: techField,
          class_grade: classGrade,
          recommended_effort: effort,
          company_eligibility: eligibility,
          notes: notes
        })
      });

      if (res.ok) {
        closeModal('modalNewCompany');
        e.target.reset();
        await loadAllData();
      }
    } catch (err) {
      console.error(err);
    }
  });

  // Form: Sprint Goals
  document.getElementById('formSprint')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!state.dashboard || !state.dashboard.daily_batch) return;
    const batchId = state.dashboard.daily_batch.id;
    const dayNo = parseInt(document.getElementById('sprintInputDayNo').value);
    const targetApp = parseInt(document.getElementById('sprintInputTargetApp').value);
    const targetEval = parseInt(document.getElementById('sprintInputTargetEval').value);
    const focus = document.getElementById('sprintInputFocus').value.trim();
    const nextPool = document.getElementById('sprintInputNextPool').value.trim();
    const status = document.getElementById('sprintInputStatus').value;

    try {
      const res = await fetch(`/api/daily-batches/${batchId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          day_no: dayNo,
          target_application: targetApp,
          target_evaluation: targetEval,
          focus: focus,
          next_pool: nextPool,
          status: status
        })
      });

      if (res.ok) {
        closeModal('modalSprint');
        await fetchDashboard();
      }
    } catch (err) {
      console.error(err);
    }
  });

  // Form: AI Configuration
  document.getElementById('aiConfigForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const model = document.getElementById('selectNvidiaModel').value;
    const feedback = document.getElementById('aiConfigFeedback');

    try {
      const res = await fetch('/api/ai/config/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nvidia_model_name: model })
      });

      if (res.ok) {
        feedback.textContent = 'Active model updated for this server session.';
        feedback.style.color = 'var(--accent-emerald)';
        await fetchAiConfig();
      }
    } catch (err) {
      console.error(err);
      feedback.textContent = 'Error saving configuration.';
      feedback.style.color = 'var(--accent-rose)';
    }
  });

  // Test NVIDIA Connection Button
  document.getElementById('btnTestAiConnection')?.addEventListener('click', async () => {
    const model = document.getElementById('selectNvidiaModel').value;
    const spinner = document.getElementById('testNvidiaSpinner');
    const box = document.getElementById('nvidiaConnectionStatusBox');
    const badge = document.getElementById('connStatusBadge');
    const latency = document.getElementById('connLatencyBadge');
    const details = document.getElementById('connStatusDetails');

    // Keep the smoke test aligned with the selected runtime model.  API keys
    // are backend-only and are never read from this page.
    if (model) {
      await fetch('/api/ai/config/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nvidia_model_name: model })
      });
    }

    spinner.style.display = 'inline-block';
    box.style.display = 'block';
    badge.textContent = 'Testing connection...';
    badge.className = 'res-class-badge class-BC';
    latency.textContent = '';
    details.textContent = `Connecting to NVIDIA NIM (${model})...`;

    try {
      const res = await fetch('/api/ai/test-connection', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        badge.textContent = 'CONNECTED';
        badge.className = 'res-class-badge class-A';
        latency.textContent = `${data.latency_ms} ms latency`;
        details.textContent = `Success! Successfully reached ${data.model} on NVIDIA NIM. AI fit scoring and feedback classification will run with live NVIDIA LLM inference.`;
      } else {
        badge.textContent = 'UNAVAILABLE';
        badge.className = 'res-class-badge class-C';
        details.textContent = data.error?.message || 'Could not reach NVIDIA API.';
      }
    } catch (err) {
      badge.textContent = 'ERROR';
      badge.className = 'res-class-badge class-D';
      details.textContent = 'Network or server error while testing connection.';
    } finally {
      spinner.style.display = 'none';
      await fetchAiConfig();
    }
  });


  // Form: Candidate Profile
  document.getElementById('candidateProfileForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('candProfileName').value.trim();
    const degree = document.getElementById('candDegree').value.trim();
    const uni = document.getElementById('candUni').value.trim();
    const target = document.getElementById('candTarget').value.trim();
    const avail = document.getElementById('candAvailability').value.trim();
    const loc = document.getElementById('candLocation').value.trim();
    const notes = document.getElementById('candNotes').value.trim();
    const feedback = document.getElementById('candidateFeedback');

    try {
      const res = await fetch('/api/candidates/current', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          profile_name: name,
          degree: degree,
          uni: uni,
          target: target,
          availability: avail,
          location: loc,
          notes: notes
        })
      });

      if (res.ok) {
        feedback.textContent = 'Profile updated!';
        feedback.style.color = 'var(--accent-emerald)';
        await fetchCandidateProfile();
      }
    } catch (err) {
      console.error(err);
      feedback.textContent = 'Error updating profile.';
      feedback.style.color = 'var(--accent-rose)';
    }
  });

  // Search filter for companies
  document.getElementById('companySearchInput')?.addEventListener('input', (e) => {
    filterCompaniesTable(e.target.value, document.getElementById('companyClassFilter').value);
  });
  document.getElementById('companyClassFilter')?.addEventListener('change', (e) => {
    filterCompaniesTable(document.getElementById('companySearchInput').value, e.target.value);
  });
}

function filterCompaniesTable(search, classGrade) {
  const s = (search || '').toLowerCase();
  const c = classGrade || '';
  const rows = document.querySelectorAll('#companiesPoolTableBody tr');
  rows.forEach(r => {
    const text = r.textContent.toLowerCase();
    const matchesSearch = !s || text.includes(s);
    const matchesClass = !c || text.includes(`class ${c.toLowerCase()}`) || text.includes(c);
    r.style.display = (matchesSearch && matchesClass) ? '' : 'none';
  });
}

function renderFitResult(data) {
  const card = document.getElementById('aiFitResultCard');
  card.style.display = 'block';

  document.getElementById('resClassBadge').textContent = `CLASS ${data.class_grade}`;
  document.getElementById('resClassBadge').className = `res-class-badge class-${formatClassClass(data.class_grade)}`;
  document.getElementById('resScoreBadge').textContent = `${data.fit_score}% Match`;
  document.getElementById('resEffortBadge').textContent = `Effort: ${data.recommended_effort}`;
  document.getElementById('resConfBadge').textContent = `Confidence: ${data.evidence_confidence}`;
  document.getElementById('resRationale').textContent = data.rationale;

  const matched = document.getElementById('resMatchedSkills');
  matched.innerHTML = '';
  (data.matched_skills || []).forEach(s => {
    const sp = document.createElement('span');
    sp.className = 'pill-item';
    sp.textContent = s;
    matched.appendChild(sp);
  });

  const missing = document.getElementById('resMissingSkills');
  missing.innerHTML = '';
  (data.missing_skills || []).forEach(s => {
    const sp = document.createElement('span');
    sp.className = 'pill-item';
    sp.textContent = s;
    missing.appendChild(sp);
  });

  const sugList = document.getElementById('resTailoringList');
  sugList.innerHTML = '';
  (data.tailoring_suggestions || []).forEach(s => {
    const li = document.createElement('li');
    li.textContent = s;
    sugList.appendChild(li);
  });
}

function renderFeedbackResult(data) {
  const card = document.getElementById('fbResultCard');
  card.style.display = 'block';

  document.getElementById('fbTypeBadge').textContent = data.feedback_type;
  document.getElementById('fbActionableBadge').textContent = `Actionable: ${data.is_actionable}`;

  const gaps = document.getElementById('fbExtractedGaps');
  gaps.innerHTML = '';
  (data.extracted_skill_gaps || []).forEach(g => {
    const sp = document.createElement('span');
    sp.className = 'pill-item';
    sp.textContent = g;
    gaps.appendChild(sp);
  });

  document.getElementById('fbActionPlan').textContent = data.action_plan_for_candidate;
  document.getElementById('fbDraftReply').value = data.polite_feedback_response_draft;
}

function populateJobPreview(preview) {
  document.getElementById('jobPreviewCompany').value = preview.company_name || '';
  document.getElementById('jobPreviewTitle').value = preview.position_title || '';
  document.getElementById('jobPreviewLocation').value = preview.location || '';
  document.getElementById('jobPreviewPlatform').value = preview.source_platform || '';
  document.getElementById('jobPreviewDescription').value = preview.job_description || '';
  document.getElementById('jobPreviewRequired').value = (preview.required_qualifications || [])
    .map(item => item.text)
    .join('\n');
  document.getElementById('jobPreviewPreferred').value = (preview.preferred_qualifications || [])
    .map(item => item.text)
    .join('\n');
  document.getElementById('jobPreviewUrl').value = preview.source_url || '';
  document.getElementById('jobConfirmFeedback').textContent = '';
}

function beginJobPreview(payload, versionSource, previousId = null, sourceHash = null) {
  state.jobIngestionPreview = payload.preview;
  state.jobIngestionSourceText = payload.source_text;
  state.jobVersionSource = versionSource;
  state.jobPreviousId = previousId;
  state.jobSourceHash = sourceHash;
  populateJobPreview(payload.preview);
  setJobPreviewEditable(true);
  document.getElementById('jobPreviewPanel').style.display = 'block';
  document.getElementById('btnConfirmJob').style.display = 'inline-block';
  document.getElementById('btnEditExistingJob').style.display = 'none';
  document.getElementById('btnConfirmJob').textContent = versionSource === 'source_update' ? 'Confirm as New Version' : 'Confirm & Save Job';
  document.getElementById('jobVersionLabel').textContent = versionSource === 'source_update' ? 'Updated source detected — Review Required' : 'UNCONFIRMED — REVIEW REQUIRED';
}

function showCvReview(payload) {
  state.cvDocumentId = payload.document.id;
  state.cvProfile = payload.profile;
  if (!payload.profile) return;
  document.getElementById('cvProfileJson').value = JSON.stringify(payload.profile, null, 2);
  document.getElementById('cvConfidence').textContent = `Semantic confidence: ${payload.profile.extraction_confidence}; parser: ${payload.document.parser_version || 'legacy'}`;
  document.getElementById('cvProfilePanel').style.display = 'block';
  document.getElementById('affindaComparisonPanel').style.display = 'none';
}

async function openCvReview(documentId) {
  if (!state.candidate?.id) return;
  const response = await fetch(`/api/documents/cv/${documentId}?candidate_id=${encodeURIComponent(state.candidate.id)}`);
  const payload = await response.json();
  if (!response.ok) { alert(payload.detail?.message || 'CV review could not be opened.'); return; }
  state.cvDocumentId = documentId;
  showCvReview(payload);
  document.getElementById('btnReprocessCv').style.display = payload.document.can_reprocess ? 'inline-block' : 'none';
  document.getElementById('cvUploadFeedback').textContent = payload.document.is_confirmed ? 'Confirmed CV profile.' : 'Review Required.';
  openModal('modalCvIngestion');
}

async function startCvReprocess(documentId, button = null) {
  if (!documentId || !state.candidate?.id || state.cvReprocessing || !confirm('Reprocess this CV using the current layout-aware parser? The locally stored PDF will be parsed again and AI extraction will run once. Your current unconfirmed review is kept if reprocessing fails.')) return;
  const target = button || document.getElementById('btnReprocessCv');
  setCvBusy(true);
  document.getElementById('cvUploadFeedback').textContent = 'Reprocessing CV with layout-aware parsing and NVIDIA analysis. This may take up to approximately two minutes...';
  try {
    const response = await fetch(`/api/documents/cv/${documentId}/reprocess`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ candidate_id: state.candidate.id }) });
    const payload = await response.json();
    if (!response.ok) { document.getElementById('cvUploadFeedback').textContent = payload.detail?.message || 'CV reprocessing failed.'; return; }
    showCvReview(payload);
    document.getElementById('cvUploadFeedback').textContent = 'Reprocessing complete — Review Required.';
    document.getElementById('btnReprocessCv').style.display = 'none';
    await fetchDocuments();
  } catch (_) { document.getElementById('cvUploadFeedback').textContent = 'CV reprocessing could not be completed.'; }
  finally { setCvBusy(false); }
}

function setCvBusy(active) {
  state.cvReprocessing = active;
  document.querySelector('#formCvUpload button[type="submit"]')?.toggleAttribute('disabled', active);
  document.getElementById('btnReprocessCv')?.toggleAttribute('disabled', active);
  document.querySelectorAll('.js-reprocess-cv').forEach(button => { button.disabled = active; });
}

async function startAffindaComparison(documentId) {
  if (!documentId || !state.candidate?.id || state.affindaComparing) return;
  const consent = 'Compare with Affinda Resume Parser?\n\nThis will send this PDF to the configured third-party resume parsing service for one analysis. Your existing CV profile will not be changed.';
  if (!confirm(consent)) return;
  setAffindaBusy(true);
  const feedback = document.getElementById('cvUploadFeedback');
  feedback.dataset.state = 'processing';
  feedback.textContent = 'Sending this PDF to Affinda for one non-persistent comparison...';
  try {
    const response = await fetch(`/api/documents/cv/${documentId}/provider-preview`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_id: state.candidate.id, provider: 'affinda' })
    });
    let payload = {};
    try { payload = await response.json(); } catch (_) { /* Use a sanitized local fallback below. */ }
    if (!response.ok) {
      const failure = showAffindaFailure(response.status, payload);
      feedback.dataset.state = 'failed';
      feedback.textContent = failure;
      return;
    }
    showAffindaComparison(documentId, payload);
    feedback.dataset.state = 'success';
    feedback.textContent = 'Affinda comparison complete. Your CV profile was not changed.';
  } catch (_) {
    feedback.dataset.state = 'failed';
    feedback.textContent = 'Affinda comparison failed — Affinda could not be reached. Start a new comparison manually if you want to try again.';
  }
  finally { setAffindaBusy(false); }
}

function setAffindaBusy(active) {
  state.affindaComparing = active;
  document.querySelectorAll('.js-compare-affinda').forEach(button => { button.disabled = active; });
}

function showAffindaFailure(httpStatus, payload) {
  const error = payload && payload.success === false ? payload : (payload?.detail || {});
  const upstreamStatus = error.upstream_status ?? httpStatus;
  const providerCode = error.provider_code || error.code || 'unknown_error';
  const fallback = upstreamStatus >= 500 ? 'Affinda parser temporarily unavailable.' : 'Affinda comparison was rejected.';
  const message = error.provider_message || error.message || fallback;
  const retry = error.retryable ? ' You may start one new comparison manually later.' : '';
  const panel = document.getElementById('affindaComparisonPanel');
  panel.innerHTML = `<div class="result-header"><span class="res-class-badge class-BC">AFFINDA COMPARISON FAILED</span></div>
    <p class="form-hint">${escapeHtml(message)}</p>
    <p class="form-hint">Upstream status: ${escapeHtml(String(upstreamStatus))} · Provider code: ${escapeHtml(String(providerCode))}</p>`;
  panel.style.display = 'block';
  openModal('modalCvIngestion');
  return `Affinda comparison failed — ${message} Status: ${upstreamStatus}. Provider code: ${providerCode}.${retry}`;
}

function showAffindaComparison(documentId, payload) {
  state.cvDocumentId = documentId;
  const panel = document.getElementById('affindaComparisonPanel');
  const metadata = {
    provider: payload.provider, latency_ms: payload.latency_ms, http_status: payload.http_status,
    credits_remaining: payload.credits_remaining, schema_version: payload.schema_version,
    classification: payload.classification, extraction_quality: payload.extraction_quality,
    coverage: payload.coverage, coverage_gaps: payload.coverage_gaps
  };
  panel.innerHTML = `<div class="result-header"><span class="res-class-badge class-BC">AFFINDA COMPARISON — NON-PERSISTENT</span></div>
    <p class="form-hint">The PDF was sent to Affinda for this one comparison. This preview does not replace the current CV review.</p>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem;">
      <div><label class="form-label">Current profile</label><pre class="textarea-text" style="white-space:pre-wrap;min-height:12rem;">${escapeHtml(JSON.stringify(payload.current_profile || {}, null, 2))}</pre></div>
      <div><label class="form-label">Affinda preview</label><pre class="textarea-text" style="white-space:pre-wrap;min-height:12rem;">${escapeHtml(JSON.stringify(payload.profile || {}, null, 2))}</pre></div>
    </div>
    <div class="form-group mt-2"><label class="form-label">Provider coverage and metadata</label><pre class="textarea-text" style="white-space:pre-wrap;">${escapeHtml(JSON.stringify(metadata, null, 2))}</pre></div>`;
  panel.style.display = 'block';
  openModal('modalCvIngestion');
}

async function openDocumentFile(documentId) {
  if (!state.candidate?.id) return;
  const url = `/api/documents/${documentId}/file?candidate_id=${encodeURIComponent(state.candidate.id)}`;
  try {
    const response = await fetch(url, { redirect: 'manual' });
    if (response.status === 307) {
      const target = response.headers.get('location');
      if (target) window.open(target, '_blank', 'noopener');
      return;
    }
    if (!response.ok) {
      const payload = await response.json();
      alert(payload.detail?.message || 'The document file is unavailable.');
      return;
    }
    const blobUrl = URL.createObjectURL(await response.blob());
    window.open(blobUrl, '_blank', 'noopener');
    setTimeout(() => URL.revokeObjectURL(blobUrl), 60000);
  } catch (_) { alert('The document file could not be opened.'); }
}

function setJobPreviewEditable(editable) {
  ['jobPreviewCompany', 'jobPreviewTitle', 'jobPreviewLocation', 'jobPreviewPlatform', 'jobPreviewDescription', 'jobPreviewRequired', 'jobPreviewPreferred', 'jobPreviewUrl']
    .forEach(id => { document.getElementById(id).disabled = !editable; });
}

function reviewedRequirements(textareaId, importance) {
  const originalItems = importance === 'required'
    ? (state.jobIngestionPreview?.required_qualifications || [])
    : (state.jobIngestionPreview?.preferred_qualifications || []);
  const originalsByText = new Map(
    originalItems.map(item => [item.text.trim().toLowerCase(), item])
  );
  return document.getElementById(textareaId).value
    .split('\n')
    .map(text => text.trim())
    .filter(Boolean)
    .map(text => {
      const original = originalsByText.get(text.toLowerCase());
      return {
        text,
        category: original?.category || null,
        importance,
        source_evidence: original?.source_evidence || null
      };
    });
}

// Global actions
window.openFitEvaluatorForCompany = function(name, field) {
  document.getElementById('aiFitCompanyName').value = name;
  document.getElementById('aiFitTechField').value = field || '';
  document.getElementById('aiFitJobTitle').value = 'Software / AI Internship';
  openModal('modalFitEvaluator');
};

window.quickApplyToCompany = function(compId, compName) {
  document.getElementById('appCompanySelect').value = compId;
  document.getElementById('appJobTitle').value = 'Internship';
  openModal('modalNewApplication');
};

window.updateApplicationStage = async function(appId, newStage) {
  let status = 'Applied';
  if (newStage === 'Preparing') status = 'Preparing';
  else if (newStage === 'Interview') status = 'Interview';
  else if (newStage === 'Offer') status = 'offer';
  else if (newStage === 'Rejected') status = 'Rejected';

  try {
    const res = await fetch(`/api/applications/${appId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        current_stage: newStage,
        status: status
      })
    });
    if (res.ok) {
      await loadAllData();
    }
  } catch (err) {
    console.error(err);
  }
};

window.deleteDocument = async function(docId) {
  if (!confirm('Delete document?')) return;
  try {
    await fetch(`/api/documents/${docId}`, { method: 'DELETE' });
    await fetchDocuments();
  } catch (err) {
    console.error(err);
  }
};

window.deleteSearchAlert = async function(alertId) {
  if (!confirm('Delete search alert?')) return;
  try {
    await fetch(`/api/search-alerts/${alertId}`, { method: 'DELETE' });
    await fetchSearchAlerts();
  } catch (err) {
    console.error(err);
  }
};

// Utilities
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function toSafeHttpUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(String(value));
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function formatClassClass(cls) {
  if (!cls) return 'B';
  if (cls.includes('B-/C') || cls.includes('BC')) return 'BC';
  return cls.replace(/[^A-Za-z]/g, '');
}

function formatEffortClass(effort) {
  if (!effort) return 'Medium';
  if (effort.includes('+')) return 'MediumPlus';
  return effort;
}

function formatLevelClass(lvl) {
  if (!lvl) return 'Intermediate';
  if (lvl.includes('Gap')) return 'Gap';
  return lvl.replace(/[^A-Za-z]/g, '');
}
