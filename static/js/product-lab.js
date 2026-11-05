(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const state = { projects: [], sessions: [], cases: [], notes: [], episode: null };
  const notice = (message) => { $('status').textContent = message || ''; };
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: 'same-origin', ...options });
    const contentType = response.headers.get('content-type') || '';
    const body = contentType.includes('json') ? await response.json() : await response.text();
    if (!response.ok) throw new Error(typeof body === 'object' ? (body.detail || JSON.stringify(body)) : body);
    return body;
  }
  const jsonOptions = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  async function run(action) {
    try { notice('Working…'); const result = await action(); notice(typeof result === 'string' ? result : 'Saved.'); }
    catch (error) { notice(error.message || 'Request failed.'); }
  }

  document.querySelectorAll('[data-tab]').forEach((button) => button.addEventListener('click', () => {
    document.querySelectorAll('[data-tab]').forEach((item) => item.setAttribute('aria-selected', String(item === button)));
    document.querySelectorAll('main > section').forEach((section) => { section.hidden = section.id !== button.dataset.tab; });
    notice('');
  }));

  async function loadProjects() {
    const [notesResult, documentsResult, researchResult] = await Promise.all([
      api('/api/notes'), api('/api/documents/library?limit=50'),
      api('/api/research/library?limit=50'),
    ]);
    [state.projects, state.sessions] = await Promise.all([api('/api/projects'), api('/api/sessions')]);
    const modelSelect = $('live-eval-form').elements.source_session;
    modelSelect.replaceChildren();
    for (const session of state.sessions.filter((item) => item.model && item.endpoint_url)) {
      const option = node('option', `${session.model} · ${session.name || 'Untitled chat'}`);
      option.value = session.id; modelSelect.append(option);
    }
    const assignableNotes = (notesResult.notes || []).filter((note) => !note.project_id || state.projects.some((project) => project.id === note.project_id));
    const assignableDocuments = (documentsResult.documents || []).filter((doc) => !doc.project_id || state.projects.some((project) => project.id === doc.project_id));
    const assignableResearch = (researchResult.research || []).filter((report) => !report.project_id || state.projects.some((project) => project.id === report.project_id));
    const list = $('project-list'); list.replaceChildren();
    if (!state.projects.length) list.append(node('p', 'No projects yet.'));
    for (const project of state.projects) {
      const card = node('article', undefined, 'card');
      card.append(node('h3', project.name), node('p', project.description || 'No description'),
                  node('small', `${project.session_count} conversations · ${project.note_count} notes · ${project.document_count} documents`));
      const actions = node('div', undefined, 'card-actions');
      const select = node('select');
      select.append(node('option', 'Choose a conversation'));
      select.firstChild.value = '';
      state.sessions.filter((session) => !session.project_id || session.project_id === project.id).forEach((session) => {
        const option = node('option', `${session.name || 'Untitled'}${session.project_id ? ' · assigned' : ''}`);
        option.value = session.id; select.append(option);
      });
      const assign = node('button', 'Assign conversation');
      assign.addEventListener('click', () => run(async () => {
        if (!select.value) throw new Error('Choose a conversation first.');
        await api(`/api/projects/${project.id}/sessions/${select.value}`, { method: 'PUT' });
        await loadProjects();
      }));
      const remove = node('button', 'Delete project');
      remove.addEventListener('click', () => run(async () => {
        if (!window.confirm(`Delete project “${project.name}”? Conversations will be kept.`)) return;
        await api(`/api/projects/${project.id}`, { method: 'DELETE' });
        await loadProjects();
      }));
      actions.append(select, assign, remove); card.append(actions); list.append(card);
      const noteActions = node('div', undefined, 'card-actions');
      const noteSelect = node('select');
      noteSelect.append(node('option', 'Choose a note')); noteSelect.firstChild.value = '';
      assignableNotes.filter((note) => !note.project_id || note.project_id === project.id).forEach((note) => {
        const option = node('option', `${note.title || 'Untitled'}${note.project_id ? ' · assigned' : ''}`);
        option.value = note.id; noteSelect.append(option);
      });
      const assignNote = node('button', 'Assign note');
      assignNote.addEventListener('click', () => run(async () => {
        if (!noteSelect.value) throw new Error('Choose a note first.');
        await api(`/api/projects/${project.id}/notes/${noteSelect.value}`, { method: 'PUT' });
        await loadProjects();
      }));
      noteActions.append(noteSelect, assignNote); card.append(noteActions);
      const documentActions = node('div', undefined, 'card-actions');
      const documentSelect = node('select');
      documentSelect.append(node('option', 'Choose a recent document')); documentSelect.firstChild.value = '';
      assignableDocuments.filter((doc) => !doc.project_id || doc.project_id === project.id).forEach((doc) => {
        const option = node('option', `${doc.title || 'Untitled'}${doc.project_id ? ' · assigned' : ''}`);
        option.value = doc.id; documentSelect.append(option);
      });
      const assignDocument = node('button', 'Assign document');
      assignDocument.addEventListener('click', () => run(async () => {
        if (!documentSelect.value) throw new Error('Choose a document first.');
        await api(`/api/projects/${project.id}/documents/${documentSelect.value}`, { method: 'PUT' });
        await loadProjects();
      }));
      documentActions.append(documentSelect, assignDocument); card.append(documentActions);
      const researchActions = node('div', undefined, 'card-actions');
      const researchSelect = node('select');
      researchSelect.append(node('option', 'Choose a recent report')); researchSelect.firstChild.value = '';
      assignableResearch.filter((report) => !report.project_id || report.project_id === project.id).forEach((report) => {
        const option = node('option', `${report.query || 'Untitled'}${report.project_id ? ' · assigned' : ''}`);
        option.value = report.id; researchSelect.append(option);
      });
      const assignResearch = node('button', 'Assign report');
      assignResearch.addEventListener('click', () => run(async () => {
        if (!researchSelect.value) throw new Error('Choose a report first.');
        await api(`/api/research/${encodeURIComponent(researchSelect.value)}/project`,
                  jsonOptions('PATCH', { project_id: project.id }));
        await loadProjects();
      }));
      const removeResearch = node('button', 'Move report to General');
      removeResearch.addEventListener('click', () => run(async () => {
        if (!researchSelect.value) throw new Error('Choose an assigned report first.');
        const report = assignableResearch.find((item) => item.id === researchSelect.value);
        if (report?.project_id !== project.id) throw new Error('Choose a report assigned to this project.');
        await api(`/api/research/${encodeURIComponent(researchSelect.value)}/project`,
                  jsonOptions('PATCH', { project_id: null }));
        await loadProjects();
      }));
      researchActions.append(researchSelect, assignResearch, removeResearch); card.append(researchActions);
    }
  }
  $('project-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    run(async () => {
      const form = new FormData(formElement);
      await api('/api/projects', jsonOptions('POST', { name: form.get('name'), description: form.get('description') }));
      formElement.reset(); await loadProjects();
    });
  });

  async function loadActions() {
    const [actions, notesResult, documentsResult, researchResult] = await Promise.all([
      api('/api/actions'), api('/api/notes'), api('/api/documents/library?limit=50'),
      api('/api/research/library?limit=50'),
    ]);
    const openNotes = (notesResult.notes || []).filter((note) => !note.archived);
    state.notes = openNotes.filter((note) => note.note_type === 'checklist');
    const sourceSelect = $('action-source-note'); sourceSelect.replaceChildren();
    sourceSelect.append(node('option', 'Choose a source note')); sourceSelect.firstChild.value = '';
    for (const note of openNotes) {
      const option = node('option', note.title || 'Untitled note');
      option.value = note.id; sourceSelect.append(option);
    }
    const documentSelect = $('action-source-document'); documentSelect.replaceChildren();
    documentSelect.append(node('option', 'Choose a recent document')); documentSelect.firstChild.value = '';
    for (const doc of documentsResult.documents || []) {
      const option = node('option', doc.title || 'Untitled document');
      option.value = doc.id; documentSelect.append(option);
    }
    const researchSelect = $('action-source-research'); researchSelect.replaceChildren();
    researchSelect.append(node('option', 'Choose a recent report')); researchSelect.firstChild.value = '';
    for (const report of researchResult.research || []) {
      const option = node('option', report.query || 'Untitled report');
      option.value = report.id; researchSelect.append(option);
    }
    const list = $('action-list'); list.replaceChildren();
    if (!actions.length) list.append(node('p', 'No pending proposals.'));
    for (const item of actions) {
      const card = node('article', undefined, 'card');
      card.append(node('h3', item.title),
                  node('small', `${item.source_kind}${item.source_ref ? ` · ${item.source_ref}` : ''}`));
      if (item.source_ref && ['note', 'document', 'research', 'email'].includes(item.source_kind)) {
        const source = node('a', 'Open source');
        let emailRef;
        if (item.source_kind === 'email') {
          try { emailRef = JSON.parse(item.source_ref); } catch (_) { /* Manual reference. */ }
        }
        const href = item.source_kind === 'note'
          ? `/#open=notes&note=${encodeURIComponent(item.source_ref)}`
          : item.source_kind === 'document'
            ? `/#document-${encodeURIComponent(item.source_ref)}`
            : item.source_kind === 'research'
              ? `/#research-${encodeURIComponent(item.source_ref)}`
              : emailRef?.uid && emailRef?.folder
                ? `/#email=${encodeURIComponent(emailRef.folder)}:${encodeURIComponent(emailRef.uid)}:${encodeURIComponent(emailRef.account_id || '')}`
                : '';
        if (href) { source.href = href; card.append(source); }
      }
      if (item.source_excerpt) card.append(node('p', item.source_excerpt));
      const actionsRow = node('div', undefined, 'card-actions');
      const select = node('select');
      select.append(node('option', 'Choose a checklist')); select.firstChild.value = '';
      for (const note of state.notes) {
        const option = node('option', note.title || 'Untitled checklist'); option.value = note.id; select.append(option);
      }
      const accept = node('button', 'Add to checklist');
      accept.addEventListener('click', () => run(async () => {
        if (!select.value) throw new Error('Choose a checklist first.');
        await api(`/api/actions/${item.id}/accept`, jsonOptions('POST', { note_id: select.value }));
        await loadActions();
      }));
      const reject = node('button', 'Reject');
      reject.addEventListener('click', () => run(async () => {
        await api(`/api/actions/${item.id}/reject`, { method: 'POST' });
        await loadActions();
      }));
      actionsRow.append(select, accept, reject); card.append(actionsRow); list.append(card);
    }
  }
  $('action-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    run(async () => {
      const form = new FormData(formElement);
      await api('/api/actions', jsonOptions('POST', {
        title: form.get('title'), source_kind: form.get('source_kind'),
        source_ref: form.get('source_ref'), source_excerpt: form.get('source_excerpt'),
      }));
      formElement.reset(); await loadActions();
    });
  });
  $('extract-note-actions').addEventListener('click', () => run(async () => {
    const noteId = $('action-source-note').value;
    if (!noteId) throw new Error('Choose a source note first.');
    const result = await api(`/api/actions/from-note/${encodeURIComponent(noteId)}`, { method: 'POST' });
    await loadActions();
    return `${result.created.length} new proposal(s) from the note; ${result.skipped} already reviewed or pending.`;
  }));
  $('extract-document-actions').addEventListener('click', () => run(async () => {
    const documentId = $('action-source-document').value;
    if (!documentId) throw new Error('Choose a source document first.');
    const result = await api(`/api/actions/from-document/${encodeURIComponent(documentId)}`, { method: 'POST' });
    await loadActions();
    return `${result.created.length} new proposal(s) from the document; ${result.skipped} already reviewed or pending.`;
  }));
  $('extract-research-actions').addEventListener('click', () => run(async () => {
    const sessionId = $('action-source-research').value;
    if (!sessionId) throw new Error('Choose a source report first.');
    const result = await api(`/api/actions/from-research/${encodeURIComponent(sessionId)}`, { method: 'POST' });
    await loadActions();
    return `${result.created.length} new proposal(s) from the report; ${result.skipped} already reviewed or pending.`;
  }));

  async function loadCases() {
    state.cases = await api('/api/evals/cases');
    const list = $('case-list');
    const selectors = [$('grade-form').elements.case_id, $('live-eval-form').elements.case_id,
                       $('history-case')];
    list.replaceChildren(); selectors.forEach((select) => select.replaceChildren());
    for (const item of state.cases) {
      const card = node('article', undefined, 'card');
      card.append(node('h3', item.name), node('p', item.prompt));
      card.append(node('small', `Expected: ${item.expected_tools.join(' → ') || 'none'} · Forbidden: ${item.forbidden_tools.join(', ') || 'none'}`));
      list.append(card);
      for (const select of selectors) {
        const option = node('option', item.name); option.value = item.id; select.append(option);
      }
    }
    if (!state.cases.length) list.append(node('p', 'No saved cases yet.'));
  }
  const commaList = (value) => String(value || '').split(',').map((item) => item.trim()).filter(Boolean);
  $('case-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    run(async () => {
      const form = new FormData(formElement);
      await api('/api/evals/cases', jsonOptions('POST', {
        name: form.get('name'), prompt: form.get('prompt'),
        expected_tools: commaList(form.get('expected_tools')),
        forbidden_tools: commaList(form.get('forbidden_tools')),
        required_text: form.get('required_text'),
      }));
      formElement.reset(); await loadCases();
    });
  });
  $('grade-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    run(async () => {
      const form = new FormData(formElement);
      const trace = JSON.parse(form.get('trace'));
      const result = await api(`/api/evals/cases/${form.get('case_id')}/grade`, jsonOptions('POST', {
        model_label: form.get('model_label'), response_text: form.get('response_text'), trace,
      }));
      await showGrade(result, form.get('case_id'));
    });
  });

  async function showGrade(result, caseId) {
    const target = $('grade-result'); target.replaceChildren();
    target.append(node('h3', result.grade.passed ? 'Passed' : 'Needs review'));
    for (const [name, passed] of Object.entries(result.grade.checks)) {
      target.append(node('p', `${passed ? '✓' : '✗'} ${name.replaceAll('_', ' ')}`));
    }
    const measures = result.grade.measurements || {};
    if (Object.keys(measures).length) {
      target.append(node('p', `Time: ${measures.response_time ?? '—'}s · Tokens: ${measures.total_tokens ?? '—'} · Context: ${measures.context_percent ?? '—'}%`));
    }
    $('history-case').value = caseId;
    await loadRunHistory();
  }
  async function loadRunHistory() {
    const caseId = $('history-case').value;
    const list = $('run-history'); list.replaceChildren();
    const left = $('compare-left'), right = $('compare-right');
    left.replaceChildren(); right.replaceChildren(); $('compare-result').replaceChildren();
    if (!caseId) { list.append(node('p', 'Save a case first.')); return; }
    const runs = await api(`/api/evals/cases/${caseId}/runs`);
    for (const item of runs) {
      const card = node('article', undefined, 'card');
      const measures = item.grade.measurements || {};
      card.append(node('h4', `${item.grade.passed ? 'Passed' : 'Needs review'} · ${item.model_label || 'Unlabeled model'}`),
                  node('small', `${item.created_at || ''} · ${item.grade.tool_count} tools · ${measures.total_tokens ?? '—'} tokens · ${measures.response_time ?? '—'}s`));
      list.append(card);
      for (const select of [left, right]) {
        const option = node('option', `${item.model_label || 'Unlabeled'} · ${item.created_at || item.id}`);
        option.value = item.id; select.append(option);
      }
    }
    if (!runs.length) list.append(node('p', 'No runs saved for this case yet.'));
    if (runs.length > 1) left.value = runs[1].id;
    $('compare-runs').disabled = runs.length < 2;
  }
  $('load-run-history').addEventListener('click', () => run(loadRunHistory));
  $('compare-runs').addEventListener('click', () => run(async () => {
    const first = $('compare-left').value, second = $('compare-right').value;
    if (!first || !second || first === second) throw new Error('Choose two different runs.');
    const compared = await api(`/api/evals/compare/${first}/${second}`);
    const target = $('compare-result'); target.replaceChildren();
    const formatDelta = (value, unit = '') => value == null ? 'unavailable' :
      `${value >= 0 ? '+' : ''}${Number(value.toFixed(2))}${unit}`;
    target.append(node('p', `Pass: ${compared.left.grade.passed} → ${compared.right.grade.passed}`),
                  node('p', `Tool calls: ${formatDelta(compared.delta.tool_count)} · Time: ${formatDelta(compared.delta.response_time, 's')} · Tokens: ${formatDelta(compared.delta.total_tokens)}`));
    for (const [name, passed] of Object.entries(compared.right.grade.checks)) {
      if (compared.left.grade.checks[name] !== passed) {
        target.append(node('p', `${name.replaceAll('_', ' ')}: ${compared.left.grade.checks[name]} → ${passed}`));
      }
    }
  }));
  $('live-eval-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    run(async () => {
      const form = new FormData(formElement);
      const caseId = String(form.get('case_id'));
      const selectedCase = state.cases.find((item) => item.id === caseId);
      const sourceSession = state.sessions.find((item) => item.id === form.get('source_session'));
      if (!selectedCase || !sourceSession) throw new Error('Choose a case and a model.');
      const newSession = new FormData();
      newSession.set('name', `[eval] ${selectedCase.name}`);
      newSession.set('endpoint_url', sourceSession.endpoint_url);
      newSession.set('model', sourceSession.model);
      newSession.set('skip_validation', 'true');
      newSession.set('rag', 'false');
      if (sourceSession.endpoint_id) newSession.set('endpoint_id', sourceSession.endpoint_id);
      if (sourceSession.project_id) newSession.set('project_id', sourceSession.project_id);
      const session = await api('/api/session', { method: 'POST', body: newSession });
      notice('Running read-only evaluation…');
      const turn = new FormData();
      turn.set('message', selectedCase.prompt);
      turn.set('session', session.id);
      turn.set('mode', 'agent');
      turn.set('plan_mode', 'true');
      const response = await fetch('/api/chat_stream', { method: 'POST', body: turn,
        headers: { Accept: 'text/event-stream' }, credentials: 'same-origin' });
      if (!response.ok) throw new Error(`Chat run failed: HTTP ${response.status}`);
      const raw = await response.text();
      if (raw.length > 1_900_000) throw new Error('Trace exceeds the evaluation limit; inspect the evaluation chat.');
      const records = raw.split(/\r?\n\r?\n/).filter((block) => block.trim()).map((block) => ({ sse: `${block}\n\n` }));
      let visible = '', finalText = '';
      for (const record of records) {
        const data = record.sse.split(/\r?\n/).filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n');
        if (!data || data === '[DONE]') continue;
        try {
          const eventData = JSON.parse(data);
          if (typeof eventData.delta === 'string') visible += eventData.delta;
          if (eventData.type === 'final_response') finalText = String(eventData.content || eventData.text || eventData.response || '');
        } catch (_) { /* Native decoder will report malformed records. */ }
      }
      const graded = await api(`/api/evals/cases/${caseId}/grade-native`, jsonOptions('POST', {
        model_label: sourceSession.model, response_text: finalText || visible, records,
      }));
      await showGrade(graded, caseId);
      return `Evaluation saved. Chat ${session.id} is available for inspection.`;
    });
  });

  function showEpisode(timeline, previewUrl) {
    state.episode = timeline;
    $('episode-result').hidden = false;
    $('episode-title').textContent = timeline.title;
    $('episode-meta').textContent = `${timeline.tracks.video.length} shots · ${timeline.duration} seconds · revision ${timeline.revision} · ${timeline.render_mode}`;
    $('source-audio-controls').hidden = timeline.render_mode !== 'transcript_rough_cut';
    $('timeline-download').href = `/api/studio/episodes/${timeline.episode_id}/timeline`;
    $('captions-download').href = `/api/studio/episodes/${timeline.episode_id}/captions.srt`;
    const video = $('episode-video'); video.hidden = !previewUrl;
    if (previewUrl) video.src = `${previewUrl}?v=${Date.now()}`; else video.removeAttribute('src');
    const list = $('shot-list'); list.replaceChildren();
    timeline.tracks.video.forEach((shot, index) => {
      const card = node('article', undefined, 'card');
      card.append(node('h3', `Shot ${index + 1}`));
      if (shot.video_path) card.append(node('small', `Source video ${shot.source_start}s–${shot.source_end}s`));
      if (shot.media_path) {
        const image = node('img');
        image.src = `/api/studio/episodes/${timeline.episode_id}/shots/${encodeURIComponent(shot.id)}/still`;
        image.alt = `Still for shot ${index + 1}`;
        image.style.cssText = 'display:block;width:100%;max-width:440px;border-radius:7px;margin:12px 0';
        card.append(image);
      }
      const title = node('input'); title.value = shot.title; title.setAttribute('aria-label', 'Shot title');
      const prompt = node('textarea'); prompt.value = shot.visual_prompt; prompt.rows = 3; prompt.setAttribute('aria-label', 'Visual prompt');
      const narration = node('textarea'); narration.value = timeline.tracks.narration[index].text; narration.rows = 3; narration.setAttribute('aria-label', 'Narration');
      const duration = node('input'); duration.type = 'number'; duration.min = '0.1'; duration.max = '30'; duration.step = '0.1'; duration.value = shot.duration; duration.setAttribute('aria-label', 'Duration in seconds');
      card.append(title, prompt, narration, duration);
      const actions = node('div', undefined, 'card-actions');
      const fileInput = node('input'); fileInput.type = 'file'; fileInput.accept = 'image/png,image/jpeg,image/webp';
      fileInput.setAttribute('aria-label', `Still image for shot ${index + 1}`);
      const upload = node('button', 'Use still image');
      upload.addEventListener('click', () => run(async () => {
        if (!fileInput.files.length) throw new Error('Choose an image first.');
        const body = new FormData(); body.append('image', fileInput.files[0]);
        body.append('expected_revision', String(timeline.revision));
        const result = await api(`/api/studio/episodes/${timeline.episode_id}/shots/${encodeURIComponent(shot.id)}/still`,
                                 { method: 'POST', body });
        showEpisode(result.timeline, result.preview_url);
      }));
      actions.append(fileInput, upload);
      const voice = timeline.tracks.narration[index];
      if (voice.source_audio) {
        card.append(node('small', `Source audio ${voice.source_start}s–${voice.source_end}s`));
      } else if (voice.audio_path) {
        const player = node('audio'); player.controls = true;
        player.src = `/api/studio/episodes/${timeline.episode_id}/shots/${encodeURIComponent(shot.id)}/narration`;
        card.append(player);
      }
      const audioInput = node('input'); audioInput.type = 'file';
      audioInput.accept = '.wav,.mp3,.m4a,.ogg,.flac';
      audioInput.setAttribute('aria-label', `Narration audio for shot ${index + 1}`);
      const uploadAudio = node('button', 'Use narration audio');
      uploadAudio.addEventListener('click', () => run(async () => {
        if (!audioInput.files.length) throw new Error('Choose an audio file first.');
        const body = new FormData(); body.append('audio', audioInput.files[0]);
        body.append('expected_revision', String(timeline.revision));
        const result = await api(`/api/studio/episodes/${timeline.episode_id}/shots/${encodeURIComponent(shot.id)}/narration`,
                                 { method: 'POST', body });
        showEpisode(result.timeline, result.preview_url);
      }));
      actions.append(audioInput, uploadAudio);
      const generateAudio = node('button', 'Generate narration');
      generateAudio.addEventListener('click', () => run(async () => {
        const text = narration.value.trim();
        if (!text) throw new Error('Enter narration text first.');
        const result = await api(`/api/studio/episodes/${timeline.episode_id}/shots/${encodeURIComponent(shot.id)}/synthesize-narration`,
                                 jsonOptions('POST', { text, expected_revision: timeline.revision }));
        showEpisode(result.timeline, result.preview_url);
      }));
      actions.append(generateAudio);
      const save = node('button', 'Save shot');
      save.addEventListener('click', () => run(async () => {
        const result = await api(`/api/studio/episodes/${timeline.episode_id}/timeline`, jsonOptions('PATCH', {
          action: 'set_shot', shot_id: shot.id, title: title.value,
          visual_prompt: prompt.value, narration_text: narration.value,
          duration: Number(duration.value), render_preview: true,
          expected_revision: timeline.revision,
        }));
        showEpisode(result.timeline, result.preview_url);
      }));
      actions.append(save);
      if (shot.duration >= 0.2) {
        const split = node('button', 'Split in half');
        split.addEventListener('click', () => run(async () => {
          const result = await api(`/api/studio/episodes/${timeline.episode_id}/timeline`, jsonOptions('PATCH', {
            action: 'split_shot', shot_id: shot.id,
            at_seconds: Number((shot.duration / 2).toFixed(3)), render_preview: true,
            expected_revision: timeline.revision,
          }));
          showEpisode(result.timeline, result.preview_url);
        }));
        actions.append(split);
      }
      if (timeline.tracks.video.length > 1) {
        const remove = node('button', 'Delete shot');
        remove.addEventListener('click', () => run(async () => {
          if (!window.confirm('Delete this shot and close the gap?')) return;
          const result = await api(`/api/studio/episodes/${timeline.episode_id}/timeline`, jsonOptions('PATCH', {
            action: 'delete_shot', shot_id: shot.id, render_preview: true,
            expected_revision: timeline.revision,
          }));
          showEpisode(result.timeline, result.preview_url);
        }));
        actions.append(remove);
      }
      if (index > 0) {
        const up = node('button', 'Move up');
        up.addEventListener('click', () => run(async () => {
          const result = await api(`/api/studio/episodes/${timeline.episode_id}/timeline`, jsonOptions('PATCH', {
            action: 'move_shot', shot_id: shot.id, index: index - 1, render_preview: true,
            expected_revision: timeline.revision,
          }));
          showEpisode(result.timeline, result.preview_url);
        }));
        actions.append(up);
      }
      card.append(actions); list.append(card);
    });
  }
  async function loadEpisodes() {
    const episodes = await api('/api/studio/episodes');
    const list = $('episode-list'); list.replaceChildren();
    if (!episodes.length) list.append(node('p', 'No saved episodes yet.'));
    for (const episode of episodes) {
      const card = node('article', undefined, 'card');
      card.append(node('h3', episode.title),
                  node('small', `${episode.shot_count} shots · ${episode.duration} seconds · revision ${episode.revision}`));
      const open = node('button', 'Open timeline');
      open.addEventListener('click', () => run(async () => {
        const timeline = await api(`/api/studio/episodes/${episode.id}/timeline`);
        showEpisode(timeline, episode.has_preview ? `/api/studio/episodes/${episode.id}/preview` : null);
      }));
      card.append(node('div', undefined, 'card-actions'));
      card.lastChild.append(open);
      list.append(card);
    }
  }
  $('episode-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    run(async () => {
      const form = new FormData(formElement);
      const result = await api('/api/studio/episodes', jsonOptions('POST', {
        title: form.get('title'), outline: form.get('outline'),
        render_preview: form.has('render_preview'),
      }));
      showEpisode(result.timeline, result.preview_url);
      await loadEpisodes();
    });
  });
  $('srt-form').addEventListener('submit', (event) => {
    event.preventDefault();
    const formElement = event.currentTarget;
    run(async () => {
      const form = new FormData(formElement);
      const result = await api('/api/studio/episodes/from-srt', { method: 'POST', body: form });
      showEpisode(result.timeline, result.preview_url);
      await loadEpisodes();
    });
  });
  $('render-episode').addEventListener('click', () => run(async () => {
    if (!state.episode) throw new Error('Open an episode first.');
    const timeline = state.episode;
    const result = await api(`/api/studio/episodes/${timeline.episode_id}/render`,
                             jsonOptions('POST', { expected_revision: timeline.revision }));
    showEpisode(result.timeline, result.preview_url);
    await loadEpisodes();
  }));
  $('upload-source-audio').addEventListener('click', () => run(async () => {
    const timeline = state.episode;
    const file = $('source-audio-file').files[0];
    if (!timeline || !file) throw new Error('Open an SRT rough cut and choose its source audio first.');
    const body = new FormData();
    body.append('audio', file);
    body.append('expected_revision', String(timeline.revision));
    const result = await api(`/api/studio/episodes/${timeline.episode_id}/source-audio`,
                             { method: 'POST', body });
    showEpisode(result.timeline, result.preview_url);
    await loadEpisodes();
  }));
  $('upload-source-video').addEventListener('click', () => run(async () => {
    const timeline = state.episode;
    const file = $('source-video-file').files[0];
    if (!timeline || !file) throw new Error('Open an SRT rough cut and choose its source video first.');
    const body = new FormData();
    body.append('video', file);
    body.append('expected_revision', String(timeline.revision));
    const result = await api(`/api/studio/episodes/${timeline.episode_id}/source-video`,
                             { method: 'POST', body });
    showEpisode(result.timeline, result.preview_url);
    await loadEpisodes();
    return 'Source video attached. Render the MP4 preview when ready.';
  }));

  if (['#actions', '#evals', '#studio'].includes(window.location.hash)) {
    document.querySelector(`[data-tab="${window.location.hash.slice(1)}"]`)?.click();
  }
  Promise.all([loadProjects(), loadActions(), loadCases(), loadEpisodes()]).catch((error) => notice(error.message || 'Could not load lab.'));
})();
