let appState = null;
let trainingMails = [];
let glossaryData = [];
let ctfChallenges = [];
let studyRoadmap = null;
let studyExercises = [];
let currentScenario = null;
let scenarioStartedAt = 0;
let currentAuthMode = 'login';
let passwordOptions = [];
let passwordQuizFinished = false;
let qrObjectUrl = null;

const badgeDefinitions = [
  { id: 'sharp-eye', label: 'Ojo clínico', icon: 'fa-eye', description: 'Identifica correctamente 3 amenazas.' },
  { id: 'account-guardian', label: 'Guardián de cuentas', icon: 'fa-user-shield', description: 'Completa 2 escenarios de cuentas o contraseñas.' },
  { id: 'safe-streak', label: 'Racha segura', icon: 'fa-fire', description: 'Toma 3 decisiones seguras consecutivas.' },
  { id: 'all-rounder', label: 'CiberGuardián integral', icon: 'fa-shield-halved', description: 'Practica en 5 tipos distintos de escenarios.' },
  { id: 'password-pro', label: 'Clave maestra', icon: 'fa-key', description: 'Completa los dos retos del laboratorio de contraseñas.' },
];

async function apiRequest(url, options = {}) {
  const requestOptions = {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
  };
  const response = await fetch(url, requestOptions);
  const isJson = response.headers.get('content-type')?.includes('application/json');
  const data = isJson ? await response.json() : null;
  if (!response.ok) {
    if (response.status === 401 && !url.startsWith('/api/auth/')) {
      showAuthGate('Tu sesión terminó. Inicia sesión de nuevo.');
    }
    throw new Error(data?.detail || 'La solicitud no se pudo completar.');
  }
  return data;
}

function setAuthMode(mode) {
  currentAuthMode = mode;
  const registering = mode === 'register';
  document.getElementById('auth-name-field').classList.toggle('d-none', !registering);
  document.getElementById('auth-institution-field').classList.toggle('d-none', !registering);
  document.getElementById('auth-login-mode').className = registering ? 'btn btn-outline-primary' : 'btn btn-primary';
  document.getElementById('auth-register-mode').className = registering ? 'btn btn-primary' : 'btn btn-outline-primary';
  document.getElementById('auth-submit').innerText = registering ? 'Crear cuenta' : 'Iniciar sesión';
  document.getElementById('auth-password').autocomplete = registering ? 'new-password' : 'current-password';
  document.getElementById('auth-password').minLength = registering ? 12 : 1;
  const help = document.getElementById('auth-password-help');
  help.innerText = registering
    ? 'Usa al menos 12 caracteres y una contraseña única.'
    : 'Introduce la contraseña de tu cuenta.';
  clearAuthMessage();
}

function showAuthMessage(message, isError = true) {
  const element = document.getElementById('auth-message');
  element.className = `small mb-3 ${isError ? 'text-danger' : 'text-success'}`;
  element.innerText = message;
}

function clearAuthMessage() {
  const element = document.getElementById('auth-message');
  element.className = 'small mb-3';
  element.innerText = '';
}

function showAuthGate(message = '') {
  document.getElementById('auth-gate').classList.remove('d-none');
  if (message) showAuthMessage(message);
}

function hideAuthGate() {
  document.getElementById('auth-gate').classList.add('d-none');
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!form.reportValidity()) return;

  const payload = {
    email: document.getElementById('auth-email').value.trim(),
    password: document.getElementById('auth-password').value,
  };
  if (currentAuthMode === 'register') {
    payload.name = document.getElementById('auth-name').value.trim();
    payload.institution = document.getElementById('auth-institution').value.trim();
    if (!payload.name || !payload.institution) {
      showAuthMessage('Completa tu nombre y la institución.');
      return;
    }
  }

  const button = document.getElementById('auth-submit');
  button.disabled = true;
  clearAuthMessage();
  try {
    await apiRequest(`/api/auth/${currentAuthMode === 'register' ? 'register' : 'login'}`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    document.getElementById('auth-password').value = '';
    await loadAuthenticatedApp();
  } catch (error) {
    showAuthMessage(error.message);
  } finally {
    button.disabled = false;
  }
}

async function logout() {
  try {
    await apiRequest('/api/auth/logout', { method: 'POST' });
    window.location.reload();
  } catch (error) {
    console.error('No se pudo cerrar la sesión en el servidor:', error);
    window.alert('No se pudo cerrar la sesión. Comprueba la conexión e inténtalo de nuevo.');
  }
}

async function loadAuthenticatedApp() {
  const [progress, scenarios, glossary, ctfs, quizOptions, roadmap, exercises] = await Promise.all([
    apiRequest('/api/progress'),
    apiRequest('/api/scenarios'),
    apiRequest('/api/glossary'),
    apiRequest('/api/ctf'),
    apiRequest('/api/password-quiz'),
    apiRequest('/api/study-roadmap'),
    apiRequest('/api/study-exercises'),
  ]);
  appState = progress;
  trainingMails = scenarios;
  glossaryData = glossary;
  ctfChallenges = ctfs;
  passwordOptions = quizOptions;
  studyRoadmap = roadmap;
  studyExercises = exercises;
  renderGlossary(glossaryData);
  renderCtfs();
  renderStudyRoadmap();
  updateUI();
  showNextScenario();
  hideAuthGate();
}

async function startSession() {
  setAuthMode('login');
  try {
    await apiRequest('/api/auth/me');
    await loadAuthenticatedApp();
  } catch (error) {
    showAuthGate();
  }
}

function switchView(viewId) {
  document.querySelectorAll('.view-section').forEach((section) => section.classList.remove('active'));
  document.querySelectorAll('.navbar-nav .nav-link').forEach((link) => link.classList.remove('active'));
  document.getElementById('view-' + viewId)?.classList.add('active');
  document.getElementById('nav-' + viewId)?.classList.add('active');
  window.scrollTo(0, 0);
  if (viewId === 'credential') generateQRCode();
  if (viewId === 'reports') updateReportsView();
}

function getRank(points) {
  if (points >= 150) return { label: 'Hacker Ético Avanzado', badgeClass: 'badge-critica' };
  if (points >= 90) return { label: 'Analista SOC Junior', badgeClass: 'badge-alta' };
  if (points >= 50) return { label: 'CiberGuardián en Formación', badgeClass: 'badge-media' };
  return { label: 'Novato en Ciberseguridad', badgeClass: 'badge-baja' };
}

function updateUI() {
  if (!appState) return;
  const rank = getRank(appState.points);
  const user = appState.user;
  const textValues = {
    'dash-student-name': user.name,
    'dash-student-inst': user.institution,
    'dash-student-id': user.id,
    'stat-points': appState.points,
    'stat-ctf': `${appState.solvedCtfs.length} / ${ctfChallenges.length}`,
    'stat-phishing': appState.phishingCompleted,
    'cred-name': user.name,
    'cred-inst': user.institution,
    'cred-xp': `${appState.points} XP`,
    'cred-id': user.id,
    'training-accuracy': `${appState.totalDecisions ? Math.round((appState.correctDecisions / appState.totalDecisions) * 100) : 0}%`,
    'badge-count': appState.badges.length,
  };
  Object.entries(textValues).forEach(([id, value]) => {
    const element = document.getElementById(id);
    if (element) element.innerText = String(value);
  });

  [
    [document.getElementById('dash-student-rank'), `badge ${rank.badgeClass} fs-6 px-3 py-1`],
    [document.getElementById('cred-rank'), `badge ${rank.badgeClass} px-2 py-1`],
  ].forEach(([element, className]) => {
    if (element) {
      element.innerText = rank.label;
      element.className = className;
    }
  });

  const certStatus = document.getElementById('stat-cert-status');
  if (certStatus) certStatus.innerText = appState.points >= 100 ? '¡Desbloqueado!' : 'En Proceso';

  const risk = Math.max(0, Math.min(100, Number(appState.vulnerability) || 0));
  const riskBar = document.getElementById('security-progress');
  const riskLabel = document.getElementById('security-label');
  if (riskBar) {
    riskBar.style.width = `${risk}%`;
    riskBar.parentElement?.setAttribute('aria-valuenow', String(risk));
    riskBar.className = `progress-bar ${risk >= 70 ? 'bg-danger' : risk >= 40 ? 'bg-warning' : 'bg-success'}`;
  }
  if (riskLabel) {
    riskLabel.innerText = risk >= 70 ? `Vulnerabilidad alta (${risk}%)` : risk >= 40 ? `Vulnerabilidad moderada (${risk}%)` : `Buena salud digital (${risk}% de riesgo)`;
  }

  const ctfBadge = document.getElementById('ctf-top-badge');
  if (ctfBadge) ctfBadge.innerText = `${appState.solvedCtfs.length} / ${ctfChallenges.length} Banderas Capturadas`;
  renderBadges();
  renderTrainingSummary();
}

function editStudentProfile() {
  document.getElementById('input-student-name').value = appState.user.name;
  document.getElementById('input-student-inst').value = appState.user.institution;
  document.getElementById('input-student-id').value = appState.user.id;
  new bootstrap.Modal(document.getElementById('profileModal')).show();
}

async function saveStudentProfile() {
  const name = document.getElementById('input-student-name').value.trim();
  const institution = document.getElementById('input-student-inst').value.trim();
  if (!name || !institution) return;
  try {
    appState = await apiRequest('/api/profile', {
      method: 'PUT',
      body: JSON.stringify({ name, institution }),
    });
    updateUI();
    bootstrap.Modal.getInstance(document.getElementById('profileModal'))?.hide();
  } catch (error) {
    window.alert(error.message);
  }
}

function getFilteredScenarios() {
  const type = document.getElementById('scenario-filter')?.value || 'all';
  return trainingMails.filter((scenario) => type === 'all' || scenario.type === type);
}

function showNextScenario() {
  const scenarios = getFilteredScenarios();
  if (!scenarios.length) {
    currentScenario = null;
    document.getElementById('mail-sender').innerText = '';
    document.getElementById('mail-subject').innerText = 'No hay escenarios disponibles para este filtro.';
    document.getElementById('mail-body').innerText = 'Elige otro tipo de entrenamiento.';
    document.getElementById('training-action-box').replaceChildren();
    return;
  }
  const currentIndex = scenarios.indexOf(currentScenario);
  const nextIndex = currentIndex < 0 ? 0 : (currentIndex + 1) % scenarios.length;
  renderScenario(scenarios[nextIndex]);
}

function renderScenario(scenario) {
  currentScenario = scenario;
  scenarioStartedAt = Date.now();
  const scenarios = getFilteredScenarios();
  const counter = document.getElementById('training-counter');
  if (counter) {
    counter.innerText = scenario.liveGenerated
      ? scenario.simulationKind === 'ai-generated'
        ? 'Variación generada con IA'
        : scenario.simulationKind === 'attack-simulation'
          ? 'Simulación defensiva · Wi-Fi'
          : 'Ejercicio dinámico · Wi-Fi'
      : `Escenario ${scenarios.indexOf(scenario) + 1} de ${scenarios.length}`;
  }
  document.getElementById('scenario-category').innerText = scenario.category;
  document.getElementById('scenario-channel').innerText = scenario.channel;
  document.getElementById('mail-sender').innerText = scenario.sender;
  document.getElementById('mail-subject').innerText = scenario.subject;
  document.getElementById('mail-body').innerText = scenario.body;

  const actionBox = document.getElementById('training-action-box');
  actionBox.classList.remove('d-none');
  actionBox.replaceChildren();
  scenario.decisions.forEach((decision, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-outline-primary text-start p-3 decision-option';
    button.innerText = decision.text;
    button.addEventListener('click', () => submitScenarioDecision(index));
    actionBox.appendChild(button);
  });

  const feedback = document.getElementById('training-feedback');
  feedback.className = 'mt-4 p-3 rounded d-none';
  feedback.replaceChildren();
  document.getElementById('btn-next-mail').classList.add('d-none');
  document.getElementById('scenario-speed').innerText = 'Analiza remitente, contexto, urgencia y datos solicitados.';
}

async function generateLiveScenario() {
  const button = document.getElementById('generate-live-scenario');
  button.disabled = true;
  try {
    const scenario = await apiRequest('/api/scenarios/live', { method: 'POST' });
    renderScenario(scenario);
    document.getElementById('scenario-speed').innerText =
      scenario.simulationKind === 'attack-simulation'
        ? 'Incidente ficticio: observa las señales y elige cómo protegerte y reportarlo. No se realiza ninguna acción en una red.'
        : 'Ejercicio ficticio generado localmente. Revisa la situación y elige una respuesta defensiva.';
  } catch (error) {
    showTrainingError(error.message);
  } finally {
    button.disabled = false;
  }
}

async function generateAiScenario() {
  if (!currentScenario) {
    showTrainingError('Primero selecciona un ejercicio para crear una variación.');
    return;
  }
  const button = document.getElementById('generate-ai-scenario');
  button.disabled = true;
  button.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Generando…';
  try {
    const scenario = await apiRequest('/api/scenarios/ai', {
      method: 'POST',
      body: JSON.stringify({ scenario_id: currentScenario.id }),
    });
    renderScenario(scenario);
    document.getElementById('scenario-speed').innerText =
      'Variación creada por OpenRouter. Las opciones y la puntuación siguen validadas por el servidor.';
  } catch (error) {
    showTrainingError(error.message);
  } finally {
    button.disabled = false;
    button.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles me-2"></i>Variación IA (API)';
  }
}

function appendFeedbackLine(parent, className, text) {
  const line = document.createElement('p');
  line.className = className;
  line.innerText = text;
  parent.appendChild(line);
}

async function submitScenarioDecision(decisionIndex) {
  if (!currentScenario) return;
  document.querySelectorAll('.decision-option').forEach((button) => { button.disabled = true; });
  try {
    const result = await apiRequest(`/api/scenarios/${encodeURIComponent(currentScenario.id)}/decision`, {
      method: 'POST',
      body: JSON.stringify({ decision_index: decisionIndex }),
    });
    appState = result.progress;
    updateUI();
    const feedback = document.getElementById('training-feedback');
    feedback.replaceChildren();
    feedback.className = `mt-4 p-3 rounded ${result.safe ? 'bg-success bg-opacity-25 border border-success text-success' : 'bg-danger bg-opacity-25 border border-danger text-danger'}`;
    appendFeedbackLine(feedback, 'fw-bold', result.safe ? '¡Decisión segura!' : 'Riesgo detectado');
    appendFeedbackLine(feedback, 'mb-2', result.feedback);
    appendFeedbackLine(feedback, 'mb-2', `Resultado de esta ruta: ${result.consequence}`);
    if (result.score > 0) appendFeedbackLine(feedback, 'mb-0 fw-semibold', `+${result.score} XP.`);
    if (result.practiceOnly) {
      appendFeedbackLine(feedback, 'small mt-2 mb-0', 'Ya recibiste los puntos por este tipo de práctica. Puedes seguir entrenando con nuevas variaciones.');
    }
    if (result.alreadyRecorded) appendFeedbackLine(feedback, 'small mt-2 mb-0', 'Esta decisión ya estaba registrada; no se otorgaron puntos adicionales.');

    if (!result.safe && result.recoveryAvailable) {
      renderRecoveryBranch(document.getElementById('training-action-box'));
      document.getElementById('scenario-speed').innerText = 'La historia continúa: elige cómo contener el incidente simulado.';
    } else {
      document.getElementById('training-action-box').classList.add('d-none');
      document.getElementById('btn-next-mail').classList.remove('d-none');
      document.getElementById('scenario-speed').innerText = 'Revisa la explicación y continúa cuando estés listo.';
    }
  } catch (error) {
    document.querySelectorAll('.decision-option').forEach((button) => { button.disabled = false; });
    showTrainingError(error.message);
  }
}

function renderRecoveryBranch(container) {
  container.replaceChildren();
  const prompt = document.createElement('p');
  prompt.className = 'fw-semibold mb-2';
  prompt.innerText = 'En esta ruta simulada, una acción de riesgo ya ocurrió. ¿Qué haces ahora?';
  container.appendChild(prompt);
  const safeRecoveryText = currentScenario?.type === 'wifi'
    ? 'Desconectarte, usar datos móviles y avisar al soporte por un canal oficial'
    : 'Detener la interacción y reportar por un canal oficial';
  [
    { safe: true, text: safeRecoveryText },
    { safe: false, text: 'Seguir las instrucciones del mensaje o la llamada' },
  ].forEach((option) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-outline-warning text-start p-3 decision-option';
    button.innerText = option.text;
    button.addEventListener('click', () => submitRecoveryDecision(option.safe));
    container.appendChild(button);
  });
}

async function submitRecoveryDecision(safe) {
  if (!currentScenario) return;
  document.querySelectorAll('.decision-option').forEach((button) => { button.disabled = true; });
  try {
    const result = await apiRequest(`/api/scenarios/${encodeURIComponent(currentScenario.id)}/recovery`, {
      method: 'POST',
      body: JSON.stringify({ safe }),
    });
    appState = result.progress;
    updateUI();
    appendFeedbackLine(
      document.getElementById('training-feedback'),
      'mt-2 fw-semibold',
      result.score ? `+${result.score} XP: ${result.feedback}` : result.feedback,
    );
    if (result.practiceOnly) {
      appendFeedbackLine(
        document.getElementById('training-feedback'),
        'small mt-2 mb-0',
        'Ya recibiste los puntos por este tipo de práctica. Puedes seguir entrenando con nuevas variaciones.',
      );
    }
    document.getElementById('training-action-box').classList.add('d-none');
    document.getElementById('btn-next-mail').classList.remove('d-none');
  } catch (error) {
    document.querySelectorAll('.decision-option').forEach((button) => { button.disabled = false; });
    showTrainingError(error.message);
  }
}

function showTrainingError(message) {
  const feedback = document.getElementById('training-feedback');
  feedback.className = 'mt-4 p-3 rounded alert alert-danger';
  feedback.innerText = message;
}

function nextTrainingMail() {
  document.getElementById('training-action-box').classList.remove('d-none');
  showNextScenario();
}

function renderGlossary(items) {
  const container = document.getElementById('glossary-container');
  container.replaceChildren();
  items.forEach((item) => {
    const gravityClass = { baja: 'badge-baja', media: 'badge-media', alta: 'badge-alta', critica: 'badge-critica' }[item.gravity] || 'badge-baja';
    const column = document.createElement('div');
    column.className = 'col-md-4';
    const card = document.createElement('article');
    card.className = 'card h-100 p-4';
    const header = document.createElement('div');
    header.className = 'd-flex justify-content-between align-items-center mb-2';
    const category = document.createElement('span');
    category.className = 'badge bg-secondary';
    category.innerText = item.category;
    const gravity = document.createElement('span');
    gravity.className = `badge ${gravityClass} text-uppercase`;
    gravity.innerText = item.gravity;
    header.append(category, gravity);
    const title = document.createElement('h5');
    title.className = 'fw-bold text-white mb-2';
    title.innerText = item.title;
    const description = document.createElement('p');
    description.className = 'text-muted small mb-0';
    description.innerText = item.desc;
    card.append(header, title, description);
    column.appendChild(card);
    container.appendChild(column);
  });
}

function filterGlossary() {
  const query = document.getElementById('glossary-search').value.toLocaleLowerCase();
  renderGlossary(glossaryData.filter((item) =>
    `${item.title} ${item.desc} ${item.category}`.toLocaleLowerCase().includes(query)
  ));
}

function createTextList(items, className = 'text-muted') {
  const list = document.createElement('ul');
  list.className = className;
  items.forEach((item) => {
    const entry = document.createElement('li');
    entry.className = 'mb-1';
    entry.innerText = item;
    list.appendChild(entry);
  });
  return list;
}

function createRoadmapDetails(title, content, initiallyOpen = false) {
  const details = document.createElement('details');
  details.className = 'card p-3 mb-3';
  details.open = initiallyOpen;
  const summary = document.createElement('summary');
  summary.className = 'fw-bold text-primary';
  summary.innerText = title;
  details.appendChild(summary);
  const body = document.createElement('div');
  body.className = 'mt-3';
  content(body);
  details.appendChild(body);
  return details;
}

function addRoadmapListSection(container, title, items) {
  const heading = document.createElement('h4');
  heading.className = 'h6 fw-bold mt-3';
  heading.innerText = title;
  container.append(heading, createTextList(items));
}

function renderStudyExercise(exercise) {
  const card = document.createElement('article');
  card.className = 'border border-secondary rounded p-3 mt-3';
  const title = document.createElement('h4');
  title.className = 'h6 fw-bold';
  title.innerText = exercise.title;
  const prompt = document.createElement('p');
  prompt.className = 'small mb-3';
  prompt.innerText = exercise.prompt;
  const options = document.createElement('div');
  options.className = 'd-grid gap-2';
  const feedback = document.createElement('p');
  feedback.className = 'small mt-3 mb-0 d-none';
  feedback.setAttribute('aria-live', 'polite');

  exercise.options.forEach((option, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-outline-secondary text-start';
    button.innerText = `${String.fromCharCode(65 + index)}. ${option}`;
    button.addEventListener('click', async () => {
      options.querySelectorAll('button').forEach((choice) => { choice.disabled = true; });
      try {
        const result = await apiRequest(
          `/api/study-exercises/${encodeURIComponent(exercise.id)}/answer`,
          {
            method: 'POST',
            body: JSON.stringify({ answer_index: index }),
          },
        );
        const isCorrect = result.correct;
        feedback.className = `small mt-3 mb-0 ${isCorrect ? 'text-success' : 'text-warning'}`;
        feedback.innerText = `${isCorrect ? 'Correcto.' : `Respuesta correcta: ${String.fromCharCode(65 + result.correctIndex)}.`} ${result.explanation}`;
      } catch (error) {
        options.querySelectorAll('button').forEach((choice) => { choice.disabled = false; });
        feedback.className = 'small mt-3 mb-0 text-danger';
        feedback.innerText = error.message;
      }
    });
    options.appendChild(button);
  });

  card.append(title, prompt, options, feedback);
  return card;
}

function renderStudyRoadmap() {
  if (!studyRoadmap) return;
  document.getElementById('roadmap-title').innerText = studyRoadmap.title;
  document.getElementById('roadmap-notice').innerText = studyRoadmap.notice;

  const semesters = document.getElementById('roadmap-semesters');
  semesters.replaceChildren();
  studyRoadmap.semesters.forEach((semester) => {
    semesters.appendChild(createRoadmapDetails(
      `Semestre ${semester.semester} — ${semester.title}`,
      (body) => {
        addRoadmapListSection(body, 'Temas técnicos', semester.cyberTopics);
        const practice = document.createElement('p');
        practice.className = 'small';
        practice.innerText = `Práctica sugerida: ${semester.practice}`;
        const outcome = document.createElement('p');
        outcome.className = 'small mb-0';
        outcome.innerText = `Al finalizar: ${semester.outcome}`;
        body.append(practice, outcome);
        const exercises = studyExercises.filter((exercise) => exercise.semester === semester.semester);
        if (exercises.length) {
          const exerciseHeading = document.createElement('h4');
          exerciseHeading.className = 'h6 fw-bold mt-4';
          exerciseHeading.innerText = 'Problemas de práctica';
          body.appendChild(exerciseHeading);
          exercises.forEach((exercise) => body.appendChild(renderStudyExercise(exercise)));
        }
      },
      semester.semester === 1,
    ));
  });

  const modules = document.getElementById('roadmap-modules');
  modules.replaceChildren();
  document.getElementById('roadmap-module-note').innerText =
    `${studyRoadmap.technicalModules.length} módulos · ${studyRoadmap.reportedTechnicalHours} horas de práctica técnica de referencia. ${studyRoadmap.technicalPlanNote}`;
  studyRoadmap.technicalModules.forEach((module) => {
    modules.appendChild(createRoadmapDetails(module.title, (body) => {
      module.submodules.forEach((submodule) => {
        const heading = document.createElement('h4');
        heading.className = 'h6 fw-bold mt-3';
        heading.innerText = submodule.title;
        const hours = document.createElement('p');
        hours.className = 'small text-muted mb-2';
        hours.innerText = submodule.hours === null
          ? 'Horas: confirmar con el plan vigente del plantel.'
          : `Horas de referencia: ${submodule.hours}`;
        body.append(heading, hours, createTextList(submodule.topics));
      });
    }));
  });

  const selfStudy = document.getElementById('roadmap-self-study');
  selfStudy.replaceChildren();
  studyRoadmap.selfStudy.forEach((stage) => {
    selfStudy.appendChild(createRoadmapDetails(stage.title, (body) => {
      body.appendChild(createTextList(stage.topics));
    }));
  });

  document.getElementById('roadmap-career-guidance').replaceChildren(
    ...studyRoadmap.careerGuidance.map((text) => {
      const entry = document.createElement('li');
      entry.className = 'mb-2';
      entry.innerText = text;
      return entry;
    }),
  );
}

function renderCtfs() {
  const container = document.getElementById('ctf-container');
  container.replaceChildren();
  ctfChallenges.forEach((ctf) => {
    const isSolved = appState.solvedCtfs.includes(ctf.id);
    const difficultyClass = ctf.difficulty === 'Baja' ? 'badge-baja' : ctf.difficulty === 'Media' ? 'badge-media' : 'badge-alta';
    const column = document.createElement('div');
    column.className = 'col-md-6';
    const card = document.createElement('div');
    card.className = 'card h-100 p-4';
    const header = document.createElement('div');
    header.className = 'd-flex justify-content-between align-items-center mb-2';
    const category = document.createElement('span');
    category.className = 'badge bg-secondary';
    category.innerText = ctf.category;
    const difficulty = document.createElement('span');
    difficulty.className = `badge ${difficultyClass}`;
    difficulty.innerText = ctf.difficulty;
    header.append(category, difficulty);
    const title = document.createElement('h5');
    title.className = 'fw-bold text-white mb-2';
    title.innerText = ctf.title;
    const description = document.createElement('p');
    description.className = 'text-muted small mb-3';
    description.innerText = ctf.desc;
    card.append(header, title, description);

    if (isSolved) {
      const solved = document.createElement('div');
      solved.className = 'alert alert-success mb-0';
      solved.innerText = '¡Reto completado! (+30 XP)';
      card.appendChild(solved);
    } else {
      const inputGroup = document.createElement('div');
      inputGroup.className = 'input-group input-group-sm';
      const input = document.createElement('input');
      input.type = 'text';
      input.className = 'form-control';
      input.id = `ctf-input-${ctf.id}`;
      input.placeholder = 'Introduce la respuesta';
      const button = document.createElement('button');
      button.className = 'btn btn-primary';
      button.innerText = 'Enviar';
      button.addEventListener('click', () => submitCtf(ctf.id));
      inputGroup.append(input, button);
      const response = document.createElement('div');
      response.id = `ctf-feedback-${ctf.id}`;
      response.className = 'small mt-2';
      card.append(inputGroup, response);
    }
    column.appendChild(card);
    container.appendChild(column);
  });
  updateUI();
}

async function submitCtf(id) {
  const input = document.getElementById(`ctf-input-${id}`);
  const feedback = document.getElementById(`ctf-feedback-${id}`);
  const button = input?.parentElement?.querySelector('button');
  if (!input || !feedback || !button) return;
  button.disabled = true;
  try {
    const result = await apiRequest(`/api/ctf/${id}/submit`, {
      method: 'POST',
      body: JSON.stringify({ answer: input.value }),
    });
    appState = result.progress;
    updateUI();
    feedback.className = `small mt-2 ${result.correct ? 'text-success fw-bold' : 'text-danger'}`;
    feedback.innerText = result.correct
      ? result.awarded ? '¡Respuesta correcta! Has ganado 30 XP.' : 'Ese reto ya estaba completado.'
      : 'Respuesta incorrecta. Sigue analizando.';
    if (result.correct) window.setTimeout(renderCtfs, 700);
  } catch (error) {
    button.disabled = false;
    feedback.className = 'small mt-2 text-danger';
    feedback.innerText = error.message;
  }
}

function renderBadges() {
  const container = document.getElementById('badges-container');
  if (!container || !appState) return;
  container.replaceChildren();
  badgeDefinitions.forEach((badge) => {
    const earned = appState.badges.includes(badge.id);
    const element = document.createElement('span');
    element.className = `badge p-2 ${earned ? 'bg-primary' : 'bg-secondary opacity-50'}`;
    element.title = badge.description;
    element.innerHTML = `<i class="fa-solid ${badge.icon} me-1"></i>${badge.label}`;
    container.appendChild(element);
  });
}

function renderTrainingSummary() {
  const element = document.getElementById('training-summary');
  if (!element || !appState) return;
  const accuracy = appState.totalDecisions
    ? Math.round((appState.correctDecisions / appState.totalDecisions) * 100)
    : 0;
  element.innerText = appState.totalDecisions
    ? `${appState.completedScenarios.length} escenarios completados · ${accuracy}% de decisiones seguras`
    : 'Aún no hay respuestas registradas.';
}

function evaluatePassword() {
  const input = document.getElementById('password-practice');
  const feedback = document.getElementById('password-feedback');
  const bar = document.getElementById('password-strength-bar');
  const password = input.value;
  if (!password) {
    feedback.innerText = 'Escribe una contraseña ficticia para iniciar la práctica.';
    return;
  }

  const normalized = password.toLocaleLowerCase();
  const commonPattern = /password|contrasena|qwerty|admin|letmein|12345|abc123|iloveyou/.test(normalized) ||
    /^(.)\1+$/.test(password) || /^(0123|1234|12345|qwer|asdf)/i.test(password);
  let score = Math.min(40, password.length * 3);
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 12;
  if (/\d/.test(password)) score += 10;
  if (/[^A-Za-z0-9]/.test(password)) score += 12;
  if (password.length >= 16) score += 20;
  if (commonPattern) score = Math.min(score, 18);
  score = Math.min(100, score);

  bar.style.width = `${score}%`;
  bar.className = `progress-bar ${score >= 70 ? 'bg-success' : score >= 40 ? 'bg-warning' : 'bg-danger'}`;
  const strength = score >= 70 ? 'más robusta' : score >= 40 ? 'mejorable' : 'débil';
  const note = commonPattern ? ' Se detectó un patrón común que facilita adivinarla.' : '';
  const estimate = commonPattern || password.length < 8
    ? 'Un diccionario o una búsqueda sencilla podría encontrar patrones así muy rápido.'
    : password.length < 12
      ? 'La resistencia depende mucho del patrón; una cadena larga y aleatoria es mejor.'
      : 'Una frase larga, única y aleatoria aumenta mucho el espacio de búsqueda.';
  feedback.innerText = `Evaluación orientativa: ${strength} (${score}/100).${note} ${estimate} No se ejecutan intentos de descifrado.`;

  input.value = '';
  apiRequest('/api/password-lab/completed', {
    method: 'POST',
    body: JSON.stringify({ completed: true }),
  }).then((result) => {
    appState = result.progress;
    updateUI();
    feedback.innerText += result.awarded ? ' El laboratorio quedó registrado: +5 XP.' : ' El laboratorio ya estaba registrado.';
  }).catch((error) => {
    feedback.innerText += ` No se pudo guardar la actividad: ${error.message}`;
  });
}

async function startPasswordQuiz() {
  const container = document.getElementById('password-quiz-options');
  const feedback = document.getElementById('password-quiz-feedback');
  container.replaceChildren();
  feedback.innerText = '';
  passwordQuizFinished = false;
  try {
    passwordOptions = await apiRequest('/api/password-quiz');
    passwordOptions.forEach((option) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn btn-outline-secondary btn-sm';
      button.innerText = option.text;
      button.addEventListener('click', () => submitPasswordQuiz(option.id, button));
      container.appendChild(button);
    });
  } catch (error) {
    feedback.className = 'small mt-2 text-danger';
    feedback.innerText = error.message;
  }
}

async function submitPasswordQuiz(optionId) {
  if (passwordQuizFinished) return;
  passwordQuizFinished = true;
  document.querySelectorAll('#password-quiz-options button').forEach((button) => { button.disabled = true; });
  const feedback = document.getElementById('password-quiz-feedback');
  try {
    const result = await apiRequest('/api/password-quiz', {
      method: 'POST',
      body: JSON.stringify({ option_id: optionId }),
    });
    appState = result.progress;
    updateUI();
    feedback.className = `small mt-2 ${result.correct ? 'text-success' : 'text-warning'}`;
    feedback.innerText = result.feedback + (result.alreadyCompleted ? '' : result.correct ? ' +10 XP.' : ' Puedes intentarlo otra vez.');
    if (!result.correct && !result.alreadyCompleted) passwordQuizFinished = false;
  } catch (error) {
    passwordQuizFinished = false;
    document.querySelectorAll('#password-quiz-options button').forEach((button) => { button.disabled = false; });
    feedback.className = 'small mt-2 text-danger';
    feedback.innerText = error.message;
  }
}

async function generateQRCode() {
  const image = document.getElementById('qr-code-img');
  try {
    const response = await fetch('/api/credential/qr', { credentials: 'same-origin' });
    if (!response.ok) throw new Error('No se pudo crear el código QR.');
    if (qrObjectUrl) URL.revokeObjectURL(qrObjectUrl);
    qrObjectUrl = URL.createObjectURL(await response.blob());
    image.src = qrObjectUrl;
  } catch (error) {
    image.alt = error.message;
  }
}

function openScannerModal() {
  new bootstrap.Modal(document.getElementById('scannerModal')).show();
}

async function updateReportsView() {
  const report = await apiRequest('/api/report');
  document.getElementById('report-phishing-count').innerText = report.phishingCasesCompleted;
  document.getElementById('report-ctf-count').innerText = `${report.ctfChallengesSolved} / ${ctfChallenges.length}`;
  document.getElementById('report-xp-count').innerText = `${report.totalPointsXP} XP`;
  document.getElementById('report-rank-text').innerText = getRank(report.totalPointsXP).label;
  const area = document.getElementById('cert-action-area');
  area.replaceChildren();
  if (report.totalPointsXP >= 100) {
    const text = document.createElement('p');
    text.className = 'text-success';
    text.innerText = 'Certificado de participación desbloqueado.';
    const button = document.createElement('button');
    button.className = 'btn btn-primary btn-lg px-4';
    button.innerText = 'Ver Certificado Digital';
    button.addEventListener('click', openDiplomaModal);
    area.append(text, button);
  } else {
    area.innerText = `Acumula al menos 100 XP (actualmente ${report.totalPointsXP} XP) para desbloquear el certificado.`;
  }
}

function openDiplomaModal() {
  document.getElementById('diploma-name').innerText = appState.user.name;
  new bootstrap.Modal(document.getElementById('diplomaModal')).show();
}

async function exportReportJSON() {
  try {
    const response = await fetch('/api/report', { credentials: 'same-origin' });
    if (!response.ok) throw new Error('No se pudo descargar el reporte.');
    const file = new Blob([await response.text()], { type: 'application/json' });
    const url = URL.createObjectURL(file);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `Reporte_CiberGuard_${appState.user.id}.json`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    window.alert(error.message);
  }
}

function handleScenarioFilter() {
  currentScenario = null;
  showNextScenario();
}

async function initializeApp() {
  document.getElementById('auth-login-mode').addEventListener('click', () => setAuthMode('login'));
  document.getElementById('auth-register-mode').addEventListener('click', () => setAuthMode('register'));
  document.getElementById('auth-form').addEventListener('submit', handleAuthSubmit);
  document.getElementById('logout-button').addEventListener('click', logout);
  document.getElementById('glossary-search').addEventListener('input', filterGlossary);
  document.getElementById('scenario-filter').addEventListener('change', handleScenarioFilter);
  document.getElementById('generate-live-scenario').addEventListener('click', generateLiveScenario);
  document.getElementById('generate-ai-scenario').addEventListener('click', generateAiScenario);
  document.getElementById('check-password').addEventListener('click', evaluatePassword);
  document.getElementById('toggle-password').addEventListener('click', () => {
    const input = document.getElementById('password-practice');
    input.type = input.type === 'password' ? 'text' : 'password';
  });
  document.getElementById('password-quiz').addEventListener('click', startPasswordQuiz);
  setAuthMode('login');
  await startSession();
}

window.addEventListener('DOMContentLoaded', initializeApp);
