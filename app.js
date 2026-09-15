/* 손해사정사 1차 데일리 기출 - 프론트엔드 로직 (서버 불필요) */
(function () {
  'use strict';

  const SUBJECTS = ['보험업법', '보험계약법', '손해사정이론'];
  const CIRCLED = ['①', '②', '③', '④', '⑤'];
  const STORE_KEY = 'sonsa-quiz-v1';
  const ALL_BANK = (window.QUESTION_BANK || []).filter(q => q && q.question && Array.isArray(q.choices) && q.answer >= 1);
  let BANK = ALL_BANK;

  /* ---------- 저장소 ---------- */
  const defaultState = () => ({
    settings: { dailyCount: 30, instant: true, prioritizeWeak: true, fromYear: 2018 },
    history: {},          // qid -> {attempts, correct, lastWrong, last}
    sessions: [],         // {date, mode, total, correct, bySubject}
    daily: {},            // 'YYYY-MM-DD' -> {ids, answers, submitted}
  });
  let S = load();
  const applyRange = () => { BANK = ALL_BANK.filter(q => !q.year || q.year >= (S.settings.fromYear || 0)); };
  applyRange();
  function load() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (!raw) return defaultState();
      const parsed = JSON.parse(raw);
      return Object.assign(defaultState(), parsed, { settings: Object.assign(defaultState().settings, parsed.settings || {}) });
    } catch (e) { return defaultState(); }
  }
  function save() { try { localStorage.setItem(STORE_KEY, JSON.stringify(S)); } catch (e) { /* ignore */ } }

  /* ---------- 유틸 ---------- */
  const $ = sel => document.querySelector(sel);
  const el = (tag, attrs = {}, ...children) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') n.className = v;
      else if (k === 'html') n.innerHTML = v;
      else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined) n.setAttribute(k, v);
    }
    for (const c of children.flat()) if (c !== null && c !== undefined) n.append(c.nodeType ? c : document.createTextNode(String(c)));
    return n;
  };
  const todayStr = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  function hashStr(s) { let h = 1779033703 ^ s.length; for (let i = 0; i < s.length; i++) { h = Math.imul(h ^ s.charCodeAt(i), 3432918353); h = (h << 13) | (h >>> 19); } return h >>> 0; }
  function mulberry32(a) { return function () { a |= 0; a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  function shuffle(arr, rnd = Math.random) { const a = arr.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; }
  const subjIdx = s => Math.max(0, SUBJECTS.indexOf(s));
  const byId = Object.fromEntries(ALL_BANK.map(q => [q.id, q]));
  const fmtTime = sec => `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;
  const isCorrect = (q, n) => n === q.answer || (Array.isArray(q.accept) && q.accept.includes(n));
  const answerLabel = q => (q.accept || [q.answer]).map(a => CIRCLED[a - 1]).join(',');
  const srcLabel = q => q.year ? `${q.year}년 제${q.round}회 · ${q.subject} ${q.num}번` : `${q.source || '예시'} · ${q.subject}`;

  /* ---------- 문제 선택 ---------- */
  // 과목 균형 + (옵션) 약점 우선: 틀린 문제·안 푼 문제에 가중치
  function pickBalanced(pool, count, rnd, prioritizeWeak) {
    const groups = SUBJECTS.map(s => pool.filter(q => q.subject === s)).filter(g => g.length);
    if (!groups.length) return [];
    const weight = q => {
      if (!prioritizeWeak) return 1;
      const h = S.history[q.id];
      if (!h) return 3;                  // 안 푼 문제
      if (h.lastWrong) return 4;         // 최근 틀림
      return h.correct / h.attempts >= 1 ? 1 : 2;
    };
    const weightedPick = (g, n) => {
      const items = g.map(q => ({ q, w: weight(q) }));
      const out = [];
      while (out.length < n && items.length) {
        const total = items.reduce((a, b) => a + b.w, 0);
        let r = rnd() * total, idx = 0;
        for (; idx < items.length; idx++) { r -= items[idx].w; if (r <= 0) break; }
        idx = Math.min(idx, items.length - 1);
        out.push(items[idx].q); items.splice(idx, 1);
      }
      return out;
    };
    const per = Math.floor(count / groups.length);
    let rem = count - per * groups.length;
    const picked = [];
    for (const g of groups) { const n = per + (rem > 0 ? 1 : 0); if (rem > 0) rem--; picked.push(...weightedPick(g, Math.min(n, g.length))); }
    // 부족하면 남은 것에서 보충
    if (picked.length < count) {
      const left = pool.filter(q => !picked.includes(q));
      picked.push(...shuffle(left, rnd).slice(0, count - picked.length));
    }
    return shuffle(picked, rnd);
  }

  /* ---------- 라우팅 ---------- */
  const app = $('#app');
  let quiz = null; // 진행 중인 세트
  let timerHandle = null;

  function nav(page, arg) {
    if (timerHandle) { clearInterval(timerHandle); timerHandle = null; }
    document.querySelectorAll('.topnav a').forEach(a => a.classList.toggle('active', a.dataset.nav === page));
    app.innerHTML = '';
    window.scrollTo(0, 0);
    ({ home: renderHome, stats: renderStats, wrong: renderWrong, settings: renderSettings, quiz: renderQuiz, result: renderResult }[page] || renderHome)(arg);
  }
  document.querySelectorAll('[data-nav]').forEach(a => a.addEventListener('click', e => { e.preventDefault(); nav(a.dataset.nav); }));

  /* ---------- 홈 ---------- */
  function renderHome() {
    const t = todayStr();
    const d = S.daily[t];
    const streak = calcStreak();
    const solvedTotal = Object.values(S.history).reduce((a, h) => a + h.attempts, 0);
    const wrongCount = Object.values(S.history).filter(h => h.lastWrong).length;
    const years = [...new Set(BANK.filter(q => q.year).map(q => q.year))].sort();

    const dailyBtnText = !d ? '오늘의 문제 시작' : d.submitted ? '오늘 결과 다시 보기' : `이어서 풀기 (${Object.keys(d.answers).length}/${d.ids.length})`;

    app.append(
      el('div', { class: 'card' },
        el('div', { class: 'row', style: 'justify-content:space-between' },
          el('div', {}, el('h2', {}, `오늘의 문제 · ${t}`), el('div', { class: 'muted' }, `매일 ${S.settings.dailyCount}문제, 3과목 균형 출제. 날짜 기준으로 고정되어 오늘은 같은 세트가 나옵니다.`)),
          el('button', { class: 'btn primary', onclick: () => startDaily() }, dailyBtnText)
        ),
        d ? el('div', { style: 'margin-top:12px' }, el('div', { class: 'progress' }, el('i', { style: `width:${Math.round(Object.keys(d.answers).length / d.ids.length * 100)}%` }))) : null
      ),
      el('div', { class: 'grid3' },
        stat(streak, '연속 학습일'),
        stat(solvedTotal, '누적 풀이'),
        stat(wrongCount, '오답 대기'),
        stat(BANK.length, '문제은행')
      ),
      el('div', { class: 'card', style: 'margin-top:16px' },
        el('h3', {}, '연습 모드'),
        el('div', { class: 'row' },
          el('label', { class: 'field' }, '과목', selectEl('practice-subject', ['전체', ...SUBJECTS])),
          el('label', { class: 'field' }, '연도', selectEl('practice-year', ['전체', ...years.map(String)])),
          el('label', { class: 'field' }, '문항 수', numberEl('practice-count', 20, 5, 120)),
          el('button', { class: 'btn', style: 'align-self:flex-end', onclick: startPractice }, '랜덤 출제')
        )
      ),
      el('div', { class: 'grid2' },
        el('div', { class: 'card' },
          el('h3', {}, '모의고사'),
          el('div', { class: 'muted', style: 'margin-bottom:10px' }, '실제 시험과 동일한 과목당 40문항(총 120문항), 120분 타이머. 채점은 마지막에 한 번에 진행되며 과목별 40점·평균 60점 합격 기준으로 판정합니다.'),
          el('button', { class: 'btn', onclick: startMock }, '모의고사 시작')
        ),
        el('div', { class: 'card' },
          el('h3', {}, '오답 다시 풀기'),
          el('div', { class: 'muted', style: 'margin-bottom:10px' }, `최근에 틀린 문제 ${wrongCount}개를 다시 풉니다. 맞히면 오답 목록에서 빠집니다.`),
          el('button', { class: 'btn', disabled: wrongCount ? null : 'disabled', onclick: () => startWrongReview() }, '오답 풀기')
        )
      ),
      bankNotice() || ''
    );
  }
  function bankNotice() {
    const official = BANK.filter(q => q.year).length;
    if (official > 0) return null;
    return el('div', { class: 'card', style: 'border-color:var(--warn);background:var(--warn-soft)' },
      el('b', {}, '아직 예시 문제만 들어 있습니다.'),
      el('div', { class: 'muted', style: 'color:#6b5300' }, '보험개발원 기출문제 파일을 data/raw 폴더에 넣고 tools/import_pdf.py를 실행하면 실제 기출문제가 문제은행에 추가됩니다. 자세한 방법은 README.md를 보세요.')
    );
  }
  const stat = (v, l) => el('div', { class: 'stat' }, el('div', { class: 'v' }, v), el('div', { class: 'l' }, l));
  const selectEl = (id, opts) => el('select', { id }, opts.map(o => el('option', { value: o }, o)));
  const numberEl = (id, v, min, max) => el('input', { id, type: 'number', value: v, min, max, style: 'width:90px' });

  /* ---------- 세트 시작 ---------- */
  function startDaily() {
    const t = todayStr();
    if (!S.daily[t]) {
      const rnd = mulberry32(hashStr(t + '|sonsa'));
      const ids = pickBalanced(BANK, S.settings.dailyCount, rnd, S.settings.prioritizeWeak).map(q => q.id);
      S.daily[t] = { ids, answers: {}, submitted: false };
      save();
    }
    const d = S.daily[t];
    quiz = { mode: 'daily', title: `오늘의 문제 · ${t}`, ids: d.ids, answers: Object.assign({}, d.answers), idx: firstUnanswered(d), instant: S.settings.instant, submitted: d.submitted };
    if (quiz.submitted) return nav('result');
    nav('quiz');
  }
  const firstUnanswered = d => { const i = d.ids.findIndex(id => !(id in d.answers)); return i < 0 ? 0 : i; };

  function startPractice() {
    const subj = $('#practice-subject').value, year = $('#practice-year').value;
    const count = Math.max(1, parseInt($('#practice-count').value, 10) || 20);
    let pool = BANK;
    if (subj !== '전체') pool = pool.filter(q => q.subject === subj);
    if (year !== '전체') pool = pool.filter(q => String(q.year) === year);
    if (!pool.length) return alert('조건에 맞는 문제가 없습니다.');
    const ids = (subj === '전체' ? pickBalanced(pool, count, Math.random, S.settings.prioritizeWeak) : shuffle(pool).slice(0, count)).map(q => q.id);
    quiz = { mode: 'practice', title: `연습 · ${subj}${year !== '전체' ? ' · ' + year + '년' : ''}`, ids, answers: {}, idx: 0, instant: S.settings.instant, submitted: false };
    nav('quiz');
  }
  function startMock() {
    const ids = [];
    for (const s of SUBJECTS) {
      const pool = BANK.filter(q => q.subject === s);
      ids.push(...shuffle(pool).slice(0, 40).map(q => q.id));
    }
    if (ids.length < 3) return alert('문제가 부족합니다.');
    quiz = { mode: 'mock', title: '모의고사', ids, answers: {}, idx: 0, instant: false, submitted: false, endsAt: Date.now() + 120 * 60 * 1000 };
    nav('quiz');
  }
  function startKeywordPractice(keywords, title) {
    const kws = keywords.map(k => k.trim()).filter(Boolean);
    const hit = q => kws.some(k => q.question.includes(k) || q.choices.some(c => c.includes(k)));
    const pool = BANK.filter(hit);
    if (!pool.length) { alert('관련 기출문제를 찾지 못했습니다: ' + kws.join(', ')); return nav('home'); }
    quiz = { mode: 'practice', title: `주제 연습 · ${title || kws[0]}`, ids: shuffle(pool).slice(0, 30).map(q => q.id), answers: {}, idx: 0, instant: true, submitted: false };
    nav('quiz');
  }
  function startWrongReview() {
    const ids = shuffle(Object.entries(S.history).filter(([id, h]) => h.lastWrong && byId[id]).map(([id]) => id));
    if (!ids.length) return alert('오답이 없습니다.');
    quiz = { mode: 'wrong', title: '오답 다시 풀기', ids, answers: {}, idx: 0, instant: true, submitted: false };
    nav('quiz');
  }

  /* ---------- 풀이 화면 ---------- */
  function renderQuiz() {
    if (!quiz) return nav('home');
    const q = byId[quiz.ids[quiz.idx]];
    if (!q) { quiz.idx = 0; return renderQuiz(); }
    const answered = quiz.answers[q.id];
    const done = Object.keys(quiz.answers).length;
    const showFeedback = quiz.instant && answered !== undefined;

    const head = el('div', { class: 'q-head' },
      el('div', { class: 'row' }, el('b', {}, quiz.title), el('span', { class: 'muted' }, `${quiz.idx + 1} / ${quiz.ids.length}`)),
      el('div', { class: 'row' },
        quiz.mode === 'mock' ? el('span', { class: 'timer', id: 'timer' }, '120:00') : null,
        el('button', { class: 'btn sm ghost', onclick: () => { if (confirm('풀이를 중단하고 홈으로 갈까요? (오늘의 문제는 진행 상황이 저장됩니다)')) nav('home'); } }, '나가기')
      )
    );
    const bar = el('div', { class: 'progress', style: 'margin-bottom:16px' }, el('i', { style: `width:${Math.round(done / quiz.ids.length * 100)}%` }));

    const choices = el('div', { class: 'choices' }, q.choices.map((c, i) => {
      const n = i + 1;
      let cls = 'choice';
      if (showFeedback) { if (isCorrect(q, n)) cls += ' correct'; else if (n === answered) cls += ' wrong'; }
      else if (n === answered) cls += ' selected';
      return el('button', { class: cls, disabled: showFeedback ? 'disabled' : null, onclick: () => choose(q, n) }, el('span', { class: 'n' }, n), el('span', {}, c));
    }));

    const fb = showFeedback ? el('div', { class: 'feedback ' + (isCorrect(q, answered) ? 'ok' : 'bad') },
      el('b', {}, isCorrect(q, answered) ? '정답입니다!' : `오답입니다. 정답은 ${answerLabel(q)}번`),
      q.explanation ? q.explanation : '') : null;

    const navBtns = el('div', { class: 'q-nav' },
      el('button', { class: 'btn', disabled: quiz.idx === 0 ? 'disabled' : null, onclick: () => { quiz.idx--; renderQuiz(); } }, '← 이전'),
      quiz.idx < quiz.ids.length - 1
        ? el('button', { class: 'btn primary', onclick: () => { quiz.idx++; renderQuiz(); } }, '다음 →')
        : el('button', { class: 'btn primary', onclick: submitQuiz }, '채점하기')
    );

    const card = el('div', { class: 'card' }, head, bar,
      el('div', { class: 'row', style: 'margin-bottom:4px' }, el('span', { class: 'pill s' + subjIdx(q.subject) }, q.subject), el('span', { class: 'muted' }, srcLabel(q))),
      el('div', { class: 'q-text' }, q.question),
      choices, fb, navBtns
    );
    app.innerHTML = '';
    app.append(card, dotGrid());
    if (quiz.mode === 'mock') startTimer();
    // 키보드: 1~4 선택, Enter 다음
    document.onkeydown = e => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
      if (['1', '2', '3', '4', '5'].includes(e.key)) { const n = +e.key; if (n <= q.choices.length && !(quiz.instant && quiz.answers[q.id] !== undefined)) choose(q, n); }
      if (e.key === 'Enter' || e.key === 'ArrowRight') { if (quiz.idx < quiz.ids.length - 1) { quiz.idx++; renderQuiz(); } }
      if (e.key === 'ArrowLeft') { if (quiz.idx > 0) { quiz.idx--; renderQuiz(); } }
    };
  }
  function dotGrid() {
    return el('div', { class: 'card' }, el('div', { class: 'muted', style: 'margin-bottom:8px' }, '문항 이동 · 키보드 1~4 선택, Enter/→ 다음, ← 이전'),
      el('div', { class: 'dot-grid' }, quiz.ids.map((id, i) => {
        const a = quiz.answers[id]; let cls = 'dot';
        if (a !== undefined) cls += quiz.instant ? (isCorrect(byId[id], a) ? ' ok' : ' bad') : ' answered';
        if (i === quiz.idx) cls += ' current';
        return el('button', { class: cls, onclick: () => { quiz.idx = i; renderQuiz(); } }, i + 1);
      })));
  }
  function choose(q, n) {
    if (quiz.instant && quiz.answers[q.id] !== undefined) return;
    quiz.answers[q.id] = n;
    if (quiz.instant) recordAnswer(q, n);
    if (quiz.mode === 'daily') { S.daily[todayStr()].answers[q.id] = n; save(); }
    renderQuiz();
  }
  function recordAnswer(q, n) {
    const h = S.history[q.id] || { attempts: 0, correct: 0, lastWrong: false, last: 0 };
    h.attempts++; if (isCorrect(q, n)) h.correct++;
    h.lastWrong = !isCorrect(q, n); h.last = Date.now();
    S.history[q.id] = h; save();
  }
  function startTimer() {
    if (timerHandle) clearInterval(timerHandle);
    const tick = () => {
      const left = Math.max(0, Math.round((quiz.endsAt - Date.now()) / 1000));
      const t = $('#timer'); if (t) t.textContent = fmtTime(left);
      if (left <= 0) { clearInterval(timerHandle); timerHandle = null; alert('시험 시간이 종료되었습니다. 자동 채점합니다.'); submitQuiz(true); }
    };
    tick(); timerHandle = setInterval(tick, 1000);
  }
  function submitQuiz(force) {
    const unanswered = quiz.ids.filter(id => quiz.answers[id] === undefined).length;
    if (!force && unanswered > 0 && !confirm(`아직 ${unanswered}문항을 풀지 않았습니다. 그래도 채점할까요? (미응답은 오답 처리)`)) return;
    if (timerHandle) { clearInterval(timerHandle); timerHandle = null; }
    if (!quiz.instant) quiz.ids.forEach(id => recordAnswer(byId[id], quiz.answers[id] ?? 0));
    quiz.submitted = true;
    if (quiz.mode === 'daily') { S.daily[todayStr()].submitted = true; }
    const bySubject = {};
    quiz.ids.forEach(id => { const q = byId[id]; const b = bySubject[q.subject] || (bySubject[q.subject] = { total: 0, correct: 0 }); b.total++; if (isCorrect(q, quiz.answers[id])) b.correct++; });
    S.sessions.push({ date: todayStr(), ts: Date.now(), mode: quiz.mode, total: quiz.ids.length, correct: Object.values(bySubject).reduce((a, b) => a + b.correct, 0), bySubject });
    save();
    document.onkeydown = null;
    nav('result');
  }

  /* ---------- 결과 ---------- */
  function renderResult() {
    if (!quiz) return nav('home');
    if (quiz.mode === 'daily') { const d = S.daily[todayStr()]; quiz.answers = Object.assign({}, d.answers); }
    const rows = SUBJECTS.map(s => { const ids = quiz.ids.filter(id => byId[id].subject === s); if (!ids.length) return null; const c = ids.filter(id => isCorrect(byId[id], quiz.answers[id])).length; return { s, total: ids.length, correct: c, score: Math.round(c / ids.length * 100) }; }).filter(Boolean);
    const total = quiz.ids.length, correct = rows.reduce((a, r) => a + r.correct, 0);
    const avg = Math.round(correct / total * 100);
    const passed = quiz.mode === 'mock' ? rows.every(r => r.score >= 40) && avg >= 60 : null;
    const wrongIds = quiz.ids.filter(id => !isCorrect(byId[id], quiz.answers[id]));

    app.append(
      el('div', { class: 'card' },
        el('h2', {}, `${quiz.title} 결과`),
        el('div', { class: 'grid3', style: 'margin:12px 0' }, stat(`${correct} / ${total}`, '정답 수'), stat(`${avg}점`, '평균 점수'), quiz.mode === 'mock' ? stat(el('span', { class: passed ? 'pass' : 'fail' }, passed ? '합격' : '불합격'), '판정 (과목 40 · 평균 60)') : stat(`${wrongIds.length}`, '오답')),
        el('table', { class: 'result-table' },
          el('thead', {}, el('tr', {}, el('th', {}, '과목'), el('th', {}, '정답/문항'), el('th', {}, '점수'))),
          el('tbody', {}, rows.map(r => el('tr', {}, el('td', {}, r.s), el('td', {}, `${r.correct} / ${r.total}`), el('td', { class: r.score < 40 ? 'fail' : '' }, `${r.score}점`))))
        ),
        el('div', { class: 'row', style: 'margin-top:16px' },
          el('button', { class: 'btn primary', onclick: () => nav('home') }, '홈으로'),
          wrongIds.length ? el('button', { class: 'btn', onclick: () => { quiz = { mode: 'wrong', title: '방금 틀린 문제 다시 풀기', ids: shuffle(wrongIds), answers: {}, idx: 0, instant: true, submitted: false }; nav('quiz'); } }, '틀린 문제 다시 풀기') : null
        )
      ),
      wrongIds.length ? el('div', { class: 'card' }, el('h3', {}, `오답 해설 (${wrongIds.length})`), wrongIds.map(id => reviewItem(byId[id], quiz.answers[id]))) : el('div', { class: 'card' }, el('div', { class: 'empty' }, '모두 맞혔습니다. 🎉'))
    );
  }
  function reviewItem(q, mine) {
    return el('div', { class: 'list-item' },
      el('div', { class: 'row' }, el('span', { class: 'pill s' + subjIdx(q.subject) }, q.subject), el('span', { class: 'muted' }, srcLabel(q))),
      el('div', { class: 't' }, q.question),
      el('div', { style: 'font-size:14px' }, q.choices.map((c, i) => el('div', { style: (isCorrect(q, i + 1) ? 'color:var(--ok);font-weight:700' : (i + 1 === mine ? 'color:var(--bad)' : 'color:var(--muted)')) }, `${CIRCLED[i]} ${c}`))),
      el('div', { class: 'muted', style: 'margin-top:6px' }, `정답 ${answerLabel(q)}${mine ? ' · 내 답 ' + CIRCLED[mine - 1] : ' · 미응답'}`),
      q.explanation ? el('div', { class: 'feedback ok', style: 'margin-top:8px' }, q.explanation) : null
    );
  }

  /* ---------- 통계 ---------- */
  function calcStreak() {
    const days = new Set(S.sessions.map(s => s.date));
    let streak = 0; const d = new Date();
    if (!days.has(todayStr())) d.setDate(d.getDate() - 1); // 오늘 아직 안 했으면 어제부터 셈
    for (; ;) { const k = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; if (!days.has(k)) break; streak++; d.setDate(d.getDate() - 1); }
    return streak;
  }
  function renderStats() {
    const per = SUBJECTS.map(s => { const ids = BANK.filter(q => q.subject === s).map(q => q.id); let att = 0, cor = 0, seen = 0; ids.forEach(id => { const h = S.history[id]; if (h) { seen++; att += h.attempts; cor += h.correct; } }); return { s, bank: ids.length, seen, att, cor, acc: att ? Math.round(cor / att * 100) : null }; });
    const recent = S.sessions.slice(-15).reverse();
    const years = {};
    BANK.forEach(q => { const k = q.year ? `${q.year}년 제${q.round}회` : (q.source || '예시'); years[k] = (years[k] || 0) + 1; });
    app.append(
      el('div', { class: 'grid3' }, stat(calcStreak(), '연속 학습일'), stat(S.sessions.length, '완료한 세트'), stat(Object.keys(S.history).length, '풀어본 문제 수')),
      el('div', { class: 'card', style: 'margin-top:16px' }, el('h3', {}, '과목별 정답률'),
        el('table', { class: 'result-table' },
          el('thead', {}, el('tr', {}, el('th', {}, '과목'), el('th', {}, '문제은행'), el('th', {}, '풀어본 문제'), el('th', {}, '누적 시도'), el('th', {}, '정답률'))),
          el('tbody', {}, per.map(r => el('tr', {}, el('td', {}, r.s), el('td', {}, r.bank), el('td', {}, r.seen), el('td', {}, r.att), el('td', { class: r.acc === null ? '' : r.acc < 40 ? 'fail' : r.acc >= 60 ? 'pass' : '' }, r.acc === null ? '-' : r.acc + '%'))))
        )),
      el('div', { class: 'card' }, el('h3', {}, '최근 세트'),
        recent.length ? el('table', { class: 'result-table' },
          el('thead', {}, el('tr', {}, el('th', {}, '날짜'), el('th', {}, '모드'), el('th', {}, '결과'))),
          el('tbody', {}, recent.map(s => el('tr', {}, el('td', {}, s.date), el('td', {}, { daily: '오늘의 문제', practice: '연습', mock: '모의고사', wrong: '오답' }[s.mode] || s.mode), el('td', {}, `${s.correct} / ${s.total} (${Math.round(s.correct / s.total * 100)}점)`))))
        ) : el('div', { class: 'empty' }, '아직 완료한 세트가 없습니다.')),
      el('div', { class: 'card' }, el('h3', {}, '문제은행 구성'), el('div', { class: 'muted' }, Object.entries(years).map(([k, v]) => `${k}: ${v}문항`).join(' · ')))
    );
  }

  /* ---------- 오답노트 ---------- */
  function renderWrong() {
    const items = Object.entries(S.history).filter(([id, h]) => h.lastWrong && byId[id]).sort((a, b) => b[1].last - a[1].last);
    app.append(el('div', { class: 'card' },
      el('div', { class: 'row', style: 'justify-content:space-between' }, el('h2', {}, `오답노트 (${items.length})`), items.length ? el('button', { class: 'btn primary', onclick: startWrongReview }, '전부 다시 풀기') : null),
      items.length ? items.map(([id, h]) => reviewItem(byId[id], null)) : el('div', { class: 'empty' }, '틀린 문제가 없습니다.')
    ));
  }

  /* ---------- 설정 ---------- */
  function renderSettings() {
    const s = S.settings;
    const count = numberEl('set-count', s.dailyCount, 5, 120);
    const yearsAll = [...new Set(ALL_BANK.filter(q => q.year).map(q => q.year))].sort();
    const fromYear = el('select', { id: 'set-from' }, yearsAll.map(y => el('option', { value: y, selected: y === s.fromYear ? 'selected' : null }, `${y}년(제${y - 1977}회)부터`)));
    const instant = el('input', { type: 'checkbox', id: 'set-instant' }); instant.checked = s.instant;
    const weak = el('input', { type: 'checkbox', id: 'set-weak' }); weak.checked = s.prioritizeWeak;
    app.append(el('div', { class: 'card' },
      el('h2', {}, '설정'),
      el('div', { style: 'display:flex;flex-direction:column;gap:14px;margin-top:12px' },
        el('label', { class: 'field' }, '오늘의 문제 문항 수 (내일부터 적용)', count),
        el('label', { class: 'field' }, '출제 범위 (기출 연도)', fromYear, el('span', { class: 'muted', style: 'font-size:12px' }, '보험업법은 2021년 금융소비자보호법 시행으로 설명의무·부당권유 등 일부 조문이 옮겨졌고, 상법 보험편은 2015년 3월 개정 이후 큰 변화가 없습니다. 오래된 회차일수록 현행 법령과 다른 답이 있을 수 있으니 범위를 조절하세요.')),
        el('label', { class: 'checkbox' }, instant, '연습·오늘의 문제에서 선택 즉시 정답 확인'),
        el('label', { class: 'checkbox' }, weak, '틀린 문제·안 푼 문제를 우선 출제'),
        el('div', { class: 'row' },
          el('button', { class: 'btn primary', onclick: () => { s.dailyCount = Math.max(5, Math.min(120, +count.value || 30)); s.instant = instant.checked; s.prioritizeWeak = weak.checked; s.fromYear = +fromYear.value || 0; save(); applyRange(); updateBankInfo(); alert('저장했습니다.'); } }, '저장'),
          el('button', { class: 'btn', onclick: exportData }, '학습 기록 내보내기'),
          el('button', { class: 'btn', onclick: () => { if (confirm('모든 학습 기록을 삭제할까요?')) { S = defaultState(); save(); nav('home'); } } }, '기록 초기화')
        )
      )));
  }
  function exportData() {
    const blob = new Blob([JSON.stringify(S, null, 2)], { type: 'application/json' });
    const a = el('a', { href: URL.createObjectURL(blob), download: `sonsa-quiz-record-${todayStr()}.json` }); document.body.append(a); a.click(); a.remove();
  }

  /* ---------- 시작 ---------- */
  function updateBankInfo() { $('#bank-info').textContent = `출제 범위 ${BANK.length}문항 / 전체 ${ALL_BANK.length}문항 (${SUBJECTS.map(s => `${s} ${BANK.filter(q => q.subject === s).length}`).join(' · ')})`; }
  updateBankInfo();
  if (!BANK.length) { app.append(el('div', { class: 'card' }, el('div', { class: 'empty' }, 'data/questions.js 에 문제가 없습니다. README.md의 가져오기 절차를 따라 주세요.'))); }
  else {
    const runHash = () => { const m = location.hash.match(/^#kw=(.+)$/); if (!m) return false; const parts = decodeURIComponent(m[1]).split('|'); history.replaceState(null, '', location.pathname); startKeywordPractice(parts.slice(1), parts[0]); return true; };
    window.addEventListener('hashchange', runHash);
    if (!runHash()) nav('home');
  }
})();
