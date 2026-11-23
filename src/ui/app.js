'use strict';

const byId = id => document.getElementById(id);
const drop = byId('drop');
const resultPanel = byId('result');
const dialog = byId('dialog');
const announcement = byId('announcement');
const phases = ['check', 'repair', 'verify'];
const steps = ['正在检查存档…', '正在修复最新存档槽…', '正在校验新存档…'];
const stepLabels = ['检查存档', '修复最新槽', '校验新存档'];

let state = { view: 'ready', ready: false, maximized: false };
let choosing = false;
let dragDepth = 0;
let dialogOrigin;

const escapeHTML = value => String(value).replace(/[&<>"']/g, char => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]
));
const icon = name => `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const button = (action, label, glyph, style = '', disabled = false) => (
  `<button type="button" class="button ${style}" data-action="${action}"${disabled ? ' disabled' : ''}>${glyph ? icon(glyph) : ''}${label}</button>`
);
const softPath = path => escapeHTML(path).replaceAll('\\', '<wbr>\\');
const pathPanel = path => `<div class="path-panel"><code>${softPath(path)}</code><button type="button" class="copy" data-action="copy">${icon('copy')}复制路径</button></div>`;
const api = () => window.pywebview.api;

function slotDetails(detail) {
  if (!detail) return '';
  return `<dl class="slot">
    <div><dt>目标存档槽</dt><dd>${escapeHTML(detail.slot)}</dd></div>
    <div><dt>游戏内保存时间</dt><dd><time datetime="${escapeHTML(detail.timeISO)}">${escapeHTML(detail.time)}</time></dd></div>
  </dl>`;
}

function progress() {
  const phase = phases.indexOf(state.phase);
  return `<div class="card" aria-busy="true">
    <div class="card-title"><span class="state-icon waiting"><span class="spinner"></span></span>
      <div><h2>${steps[phase]}</h2><p><code>${escapeHTML(state.file)}</code></p></div>
    </div>
    <ol class="progress-track" aria-label="修复步骤">${stepLabels.map((label, i) =>
      `<li class="${i === phase ? 'current' : i < phase ? 'done' : ''}"${i === phase ? ' aria-current="step"' : ''}>${label}</li>`).join('')}</ol>
    ${slotDetails(state.detail)}
  </div>`;
}

function saveFeedback() {
  const feedback = state.save;
  if (!feedback) return '';
  if (feedback.status === 'pending') {
    return '<section class="save-feedback pending" aria-label="另存状态"><div class="feedback-title"><span class="spinner"></span>正在写入并校验存档…</div></section>';
  }
  if (feedback.status === 'failed') {
    return `<section class="save-feedback error" aria-label="另存状态">
      <div class="feedback-title">${icon('alert')}另存失败</div><p>${escapeHTML(feedback.message)}</p>
      ${feedback.path ? pathPanel(feedback.path) : ''}
      <div class="actions">${button('save', '重新选择文件夹…', 'folder')}</div>
    </section>`;
  }
  return `<section class="save-feedback" aria-label="另存状态">
    <div class="feedback-title">${icon('check')}已另存</div>${pathPanel(feedback.path)}
    <div class="actions">${button('open-saved', '打开所在文件夹', 'open')}</div>
  </section>`;
}

function success() {
  const detail = state.detail;
  const reward = detail.refunded
    ? '已收回「刺骨混沌」，并返还 1 个「最初的混沌容器」。'
    : '已收回未铸魂的「刺骨混沌」。';
  const loadNote = detail.continueSlot !== detail.slot
    ? `<div class="load-note">${icon('info')}<p><strong>请从「载入游戏」选择「${escapeHTML(detail.slot)}」。</strong>${detail.continueSlot ? `「继续游戏」当前指向「${escapeHTML(detail.continueSlot)}」。` : ''}</p></div>`
    : '';
  return `<div class="card">
    <div class="card-title"><span class="state-icon success">${icon('check')}</span>
      <div><h2>修复完成</h2><p>已通过回读校验</p></div>
    </div>
    <div class="result-details">
      ${slotDetails(detail)}
      <div class="summary">
        <p>已恢复雪天镜林的玉琮第二战，「三面混沌」已恢复为进行中。</p>
        <p>${reward}</p><p class="help-text">意识尘埃余额沿用原存档。</p>
      </div>
    </div>
    ${loadNote}
    <div class="result-path"><p class="path-label">生成位置</p>${pathPanel(detail.path)}</div>
    <div class="actions">
      ${button('save', '另存到文件夹…', 'folder', 'primary', state.save?.status === 'pending')}
      ${button('open-output', '打开生成位置', 'open')}
    </div>
    ${saveFeedback()}
  </div>`;
}

function failure() {
  return `<div class="card">
    <div class="card-title"><span class="state-icon error">${icon('alert')}</span>
      <div><h2>${escapeHTML(state.title)}</h2>${state.file ? `<p><code>${escapeHTML(state.file)}</code></p>` : ''}</div>
    </div>
    ${slotDetails(state.detail)}
    <div class="error-copy"><p>${escapeHTML(state.message)}</p></div>
    ${state.locate ? `<div class="actions">${button('locate', '定位游戏程序…', 'folder', 'primary')}</div>` : ''}
  </div>`;
}

function updateDrop() {
  drop.disabled = !state.ready || choosing || state.view === 'processing' || state.save?.status === 'pending';
}

function render() {
  byId('window-content').dataset.view = state.view;
  updateDrop();
  drop.classList.toggle('compact', state.view !== 'ready');
  drop.classList.remove('is-over');
  dragDepth = 0;
  if (state.view === 'processing') resultPanel.innerHTML = progress();
  else if (state.view === 'success') resultPanel.innerHTML = success();
  else if (state.view === 'error') resultPanel.innerHTML = failure();
}

function renderControls() {
  const restoreFocus = document.activeElement?.dataset.action === 'maximize';
  const control = (action, label, glyph) => `<button type="button" data-action="${action}" title="${label}" aria-label="${label}">${icon(glyph)}</button>`;
  const max = state.maximized;
  byId('window-controls').innerHTML = control('minimize', '最小化', 'minus') +
    control('maximize', max ? '还原窗口' : '最大化', max ? 'restore' : 'max') +
    control('close-window', '关闭窗口', 'close');
  if (restoreFocus) byId('window-controls').querySelector('[data-action="maximize"]').focus();
}

function focusResult(scrollToActions = false) {
  const target = resultPanel.querySelector('h2');
  if (!target) return;
  target.tabIndex = -1;
  target.focus({ preventScroll: true });
  const landmark = scrollToActions ? resultPanel.querySelector('.actions') : target;
  landmark?.scrollIntoView({ block: 'nearest' });
}

function showDialog(title, body) {
  dialogOrigin = document.activeElement;
  dialog.innerHTML = `<div class="dialog-head"><h2 class="dialog-title" id="dialog-title">${title}</h2>
    <button type="button" class="icon-button" data-action="dismiss" aria-label="关闭">${icon('close')}</button></div>
    <div class="dialog-body">${body}</div>`;
  dialog.showModal();
  dialog.querySelector('[data-action="cancel"]')?.focus();
}

function closeDialog(restoreFocus = true) {
  dialog.close();
  if (restoreFocus && dialogOrigin?.isConnected) dialogOrigin.focus();
}

function dismissDialog() {
  closeDialog();
  void api().cancel_overwrite();
}

window.updateRepairUI = event => {
  switch (event.type) {
    case 'ready':
      state.ready = true;
      updateDrop();
      break;
    case 'window':
      state.maximized = event.maximized;
      renderControls();
      break;
    case 'progress':
      state = { ...state, ...event, view: 'processing', save: null };
      render();
      announcement.textContent = steps[phases.indexOf(event.phase)];
      break;
    case 'error':
    case 'success':
      state = { ...state, ...event, view: event.type, save: null };
      render();
      focusResult(event.type === 'success');
      announcement.textContent = event.title || '修复完成。';
      break;
    case 'save':
      state.save = event;
      render();
      if (event.status !== 'pending') {
        const feedback = resultPanel.querySelector('.save-feedback');
        feedback.tabIndex = -1;
        feedback.focus();
        feedback.scrollIntoView({ block: 'nearest' });
      }
      break;
    case 'overwrite':
      showDialog('覆盖现有存档？', `<p>所选文件夹已有同名文件。</p>
        <code class="dialog-path">${softPath(event.path)}</code>
        ${event.game ? `<aside class="backup">${icon('shield')}<p><strong>这是游戏的正式存档目录。</strong>请先备份原存档并退出游戏。</p></aside>` : ''}
        <div class="actions dialog-actions">${button('cancel', '取消')}${button('approve', '覆盖', '', 'primary')}</div>`);
      break;
    case 'notice':
      showDialog(escapeHTML(event.title), `<p>${escapeHTML(event.message)}</p>
        <div class="actions dialog-actions">${button('cancel', '关闭')}</div>`);
      break;
  }
};

async function nativeAction(action) {
  if (choosing) return;
  choosing = true;
  updateDrop();
  try {
    await api()[action]();
  } catch {
    window.updateRepairUI({ type: 'notice', title: '操作未完成', message: '请重试此操作。' });
  } finally {
    choosing = false;
    updateDrop();
  }
}

async function copyPath(control) {
  const path = control.closest('.path-panel').querySelector('code');
  const copied = await api().copy_text(path.textContent).catch(() => false);
  if (copied) {
    control.innerHTML = `${icon('check')}已复制`;
    announcement.textContent = '已复制路径。';
    setTimeout(() => { control.innerHTML = `${icon('copy')}复制路径`; }, 1500);
  } else {
    const range = document.createRange();
    range.selectNodeContents(path);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    announcement.textContent = '已选中路径，可按 Ctrl+C 复制。';
  }
}

drop.addEventListener('click', () => nativeAction('choose_save'));

const fileDrag = event => event.dataTransfer?.types.includes('Files');
for (const name of ['dragover', 'drop']) {
  window.addEventListener(name, event => { if (fileDrag(event)) event.preventDefault(); });
}
drop.addEventListener('dragenter', event => {
  if (drop.disabled || !fileDrag(event)) return;
  event.preventDefault();
  dragDepth++;
  drop.classList.add('is-over');
});
drop.addEventListener('dragleave', () => {
  if (dragDepth > 0 && --dragDepth === 0) drop.classList.remove('is-over');
});
drop.addEventListener('dragover', event => {
  if (!fileDrag(event)) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = drop.disabled ? 'none' : 'copy';
});
drop.addEventListener('drop', event => {
  dragDepth = 0;
  drop.classList.remove('is-over');
  if (!drop.disabled && event.dataTransfer.files.length) {
    window.chrome.webview.postMessageWithAdditionalObjects('FilesDropped', event.dataTransfer.files);
  }
});

dialog.addEventListener('cancel', event => {
  event.preventDefault();
  dismissDialog();
});

document.addEventListener('click', event => {
  const control = event.target.closest('button[data-action]');
  if (!control) return;
  switch (control.dataset.action) {
    case 'copy': copyPath(control); break;
    case 'save': nativeAction('choose_destination'); break;
    case 'locate': nativeAction('locate_game'); break;
    case 'approve':
      closeDialog(false);
      nativeAction('approve_overwrite');
      break;
    case 'open-output': nativeAction('open_output'); break;
    case 'open-saved': nativeAction('open_saved'); break;
    case 'dismiss':
    case 'cancel': dismissDialog(); break;
    case 'minimize': api().window_action('minimize'); break;
    case 'maximize': api().window_action('maximize'); break;
    case 'close-window': api().window_action('close'); break;
  }
});

renderControls();
