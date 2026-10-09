const state = {
  apiBase: window.__API_BASE__ || localStorage.getItem('platformApiBase') || window.location.origin,
  auth: loadAuth(),
  players: [],
  dragging: false,
  selectedPlayerId: null,
};

const dom = {};

document.addEventListener('DOMContentLoaded', () => {
  cacheDom();
  initBackLink();
  initKeyboardControls();
  loadPlayback();
});

function cacheDom() {
  dom.backLink = document.getElementById('back-link');
  dom.title = document.getElementById('video-title');
  dom.meta = document.getElementById('video-meta');
  dom.status = document.getElementById('player-status');
  dom.players = document.getElementById('players-container');
}

function initBackLink() {
  if (dom.backLink) {
    dom.backLink.href = '/platform.html';
  }
}

function initKeyboardControls() {
  document.addEventListener('keydown', (event) => {
    const tag = event.target?.tagName?.toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;

    if (event.code === 'Space') {
      event.preventDefault();
      toggleGroupPlayback();
      return;
    }
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      stepGroupFrames(-1);
      return;
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault();
      stepGroupFrames(1);
    }
  });
}

async function loadPlayback() {
  const params = new URLSearchParams(window.location.search);
  const id = params.get('id');
  if (!id) {
    setStatus('缺少视频 ID');
    return;
  }
  if (!state.auth?.accessToken) {
    setStatus('请先登录后再播放视频');
    return;
  }

  try {
    setStatus('');
    const data = await apiFetch(`/videos/web/${encodeURIComponent(id)}/play`);
    const items = Array.isArray(data.videos) && data.videos.length
      ? data.videos
      : [{ video: data.video, draw_json: data.draw_json, multi_draw_json: data.multi_draw_json }];
    renderVideoInfo(items);
    renderGroupPlayer(items);
  } catch (err) {
    setStatus(parseError(err));
  }
}

function renderVideoInfo(items) {
  const video = items[0]?.video || {};
  const title = video.title || video.name || '视频播放';
  const meta = [
    video.resolution || '',
    video.fps ? `${Number(video.fps).toFixed(3).replace(/0+$/, '').replace(/\.$/, '')} fps` : '',
    video.photo_at ? formatDateTime(video.photo_at) : formatDateTime(video.created_at),
    items.length > 1 ? `同组 ${items.length} 个视频` : '',
  ].filter(Boolean).join(' · ');

  if (dom.title) dom.title.textContent = title;
  if (dom.meta) dom.meta.textContent = meta;
  document.title = `${title} - SwingPro2`;
}

function renderGroupPlayer(items) {
  cleanupPlayers();
  if (!dom.players) return;
  dom.players.innerHTML = '';

  const shell = document.createElement('section');
  shell.className = 'player-shell group-player-shell';

  const grid = document.createElement('div');
  grid.className = 'player-grid';
  grid.style.setProperty('--player-count', String(Math.min(Math.max(items.length, 1), 3)));

  items.forEach((item, index) => {
    const player = createVideoPanel(item, index);
    state.players.push(player);
    grid.appendChild(player.root);
    loadPlayerSource(player);
  });

  shell.appendChild(grid);
  shell.appendChild(createGroupControls());
  dom.players.appendChild(shell);
  updateGroupTimeline();
}

function cleanupPlayers() {
  state.players.forEach((player) => {
    player.video.pause();
    player.video.removeAttribute('src');
    player.video.load();
  });
  state.players = [];
}

function createVideoPanel(item, index) {
  const videoData = item.video || {};
  const root = document.createElement('article');
  root.className = 'player-panel';

  const label = document.createElement('div');
  label.className = 'player-label';
  label.textContent = videoData.is_primary_video === false ? `从视频 ${index}` : '主视频';

  const stage = document.createElement('div');
  stage.className = 'player-stage';
  const video = document.createElement('video');
  video.playsInline = true;
  video.preload = 'auto';
  stage.append(video, label);
  root.appendChild(stage);

  const player = {
    id: String(videoData.id ?? index),
    root,
    video,
    videoData,
    fps: 30,
  };

  const selector = document.createElement('button');
  selector.type = 'button';
  selector.className = 'player-select-dot';
  selector.setAttribute('aria-label', '选中此视频单独控制');
  selector.addEventListener('click', (event) => {
    event.stopPropagation();
    toggleSelectedPlayer(player);
  });
  stage.appendChild(selector);

  video.addEventListener('loadedmetadata', () => handleVideoMetadata(player));
  video.addEventListener('timeupdate', () => updateGroupTimeline());
  video.addEventListener('play', updateGroupPlayButton);
  video.addEventListener('pause', updateGroupPlayButton);
  video.addEventListener('ended', updateGroupPlayButton);

  return player;
}

function createGroupControls() {
  const controls = document.createElement('div');
  controls.className = 'player-controls';
  controls.innerHTML = `
    <div class="timeline-row">
      <span id="time-current">00:00.000</span>
      <input id="timeline" type="range" min="0" max="1000" value="0" step="1" aria-label="播放进度" />
      <span id="time-duration">00:00.000</span>
    </div>
    <div class="control-row">
      <button type="button" class="control-btn sync-btn" id="sync-to-primary">同步至主视频</button>
      <div class="frame-group" role="group" aria-label="逐帧播放">
        <button type="button" class="control-btn" data-action="prev5">上五帧</button>
        <button type="button" class="control-btn" data-action="prev">上一帧</button>
        <button type="button" class="control-btn primary" id="play-toggle">播放</button>
        <button type="button" class="control-btn" data-action="next">下一帧</button>
        <button type="button" class="control-btn" data-action="next5">下五帧</button>
      </div>
      <div class="rate-group" role="group" aria-label="播放倍速">
        <button type="button" class="rate-btn" data-rate="0.1">0.1x</button>
        <button type="button" class="rate-btn" data-rate="0.2">0.2x</button>
        <button type="button" class="rate-btn" data-rate="0.5">0.5x</button>
        <button type="button" class="rate-btn active" data-rate="1">1.0x</button>
      </div>
    </div>
  `;

  dom.timeline = controls.querySelector('#timeline');
  dom.timeCurrent = controls.querySelector('#time-current');
  dom.timeDuration = controls.querySelector('#time-duration');
  dom.playToggle = controls.querySelector('#play-toggle');
  dom.syncToPrimary = controls.querySelector('#sync-to-primary');
  dom.rateButtons = Array.from(controls.querySelectorAll('.rate-btn'));

  controls.querySelector('[data-action="prev5"]')?.addEventListener('click', () => stepGroupFrames(-5));
  controls.querySelector('[data-action="prev"]')?.addEventListener('click', () => stepGroupFrames(-1));
  dom.playToggle?.addEventListener('click', toggleGroupPlayback);
  dom.syncToPrimary?.addEventListener('click', syncToPrimary);
  controls.querySelector('[data-action="next"]')?.addEventListener('click', () => stepGroupFrames(1));
  controls.querySelector('[data-action="next5"]')?.addEventListener('click', () => stepGroupFrames(5));

  dom.rateButtons.forEach((btn) => {
    btn.addEventListener('click', () => setGroupPlaybackRate(Number(btn.dataset.rate || 1)));
  });

  dom.timeline?.addEventListener('input', () => {
    state.dragging = true;
    seekGroupFromTimeline();
  });
  dom.timeline?.addEventListener('change', () => {
    seekGroupFromTimeline();
    state.dragging = false;
  });

  return controls;
}

function loadPlayerSource(player) {
  const source = resolveUrl(player.videoData?.file_url || player.videoData?.file_path);
  if (!source) {
    setStatus('当前视频暂无可播放链接');
    return;
  }
  player.video.removeAttribute('controls');
  player.video.src = source;
  player.video.playbackRate = 1;
  player.video.load();
}

function handleVideoMetadata(player) {
  const fps = Number(player.videoData?.fps);
  player.fps = Number.isFinite(fps) && fps > 0 ? fps : 30;
  updateGroupTimeline();
}

function toggleGroupPlayback() {
  const playable = getControlTargets().filter((player) => player.video.src);
  if (!playable.length) return;
  const shouldPlay = playable.some((player) => player.video.paused || player.video.ended);

  playable.forEach((player) => {
    if (shouldPlay) {
      player.video.play().catch((err) => setStatus(parseError(err)));
    } else {
      player.video.pause();
    }
  });
  updateGroupPlayButton();
}

function updateGroupPlayButton() {
  if (!dom.playToggle) return;
  const playable = getControlTargets().filter((player) => player.video.src);
  const playing = playable.some((player) => !player.video.paused && !player.video.ended);
  dom.playToggle.textContent = playing ? '暂停' : '播放';
}

function setGroupPlaybackRate(rate) {
  if (!Number.isFinite(rate) || rate <= 0) return;
  getControlTargets().forEach((player) => {
    try {
      player.video.playbackRate = rate;
      setStatus('');
    } catch (err) {
      setStatus(parseError(err));
    }
  });
  dom.rateButtons?.forEach((btn) => {
    btn.classList.toggle('active', Number(btn.dataset.rate || 1) === rate);
  });
}

function stepGroupFrames(direction) {
  const base = getTimelinePlayer();
  if (!base?.video?.duration) return;
  pauseGroup();
  const frame = 1 / (base.fps || 30);
  const next = clamp(base.video.currentTime + direction * frame, 0, base.video.duration);
  seekGroupToTime(next);
}

function pauseGroup() {
  getControlTargets().forEach((player) => player.video.pause());
  updateGroupPlayButton();
}

function seekGroupFromTimeline() {
  const base = getTimelinePlayer();
  if (!base?.video?.duration || !dom.timeline) return;
  const ratio = Number(dom.timeline.value || 0) / Number(dom.timeline.max || 1000);
  seekGroupToTime(clamp(ratio * base.video.duration, 0, base.video.duration));
}

function seekGroupToTime(time) {
  getControlTargets().forEach((player) => {
    if (!player.video.duration) return;
    player.video.currentTime = clamp(time, 0, player.video.duration);
  });
  updateGroupTimeline();
}

function updateGroupTimeline() {
  const base = getTimelinePlayer();
  if (!base) return;
  const duration = Number.isFinite(base.video.duration) ? base.video.duration : 0;
  const current = Number.isFinite(base.video.currentTime) ? base.video.currentTime : 0;
  if (dom.timeCurrent) dom.timeCurrent.textContent = formatTime(current);
  if (dom.timeDuration) dom.timeDuration.textContent = formatTime(duration);
  if (dom.timeline && !state.dragging) {
    const max = Number(dom.timeline.max || 1000);
    dom.timeline.value = duration > 0 ? String(Math.round((current / duration) * max)) : '0';
  }
}

function getTimelinePlayer() {
  const selected = getSelectedPlayer();
  if (selected) return selected;
  return getPrimaryPlayer() || state.players.find((player) => Number.isFinite(player.video.duration) && player.video.duration > 0) || state.players[0] || null;
}

function getPrimaryPlayer() {
  return state.players.find((player) => player.videoData?.is_primary_video !== false) || state.players[0] || null;
}

function getSelectedPlayer() {
  if (!state.selectedPlayerId) return null;
  return state.players.find((player) => player.id === state.selectedPlayerId) || null;
}

function getControlTargets() {
  const selected = getSelectedPlayer();
  return selected ? [selected] : state.players;
}

function toggleSelectedPlayer(player) {
  state.selectedPlayerId = state.selectedPlayerId === player.id ? null : player.id;
  syncSelectedPlayerUI();
  updateGroupTimeline();
  updateGroupPlayButton();
}

function syncSelectedPlayerUI() {
  state.players.forEach((player) => {
    player.root.classList.toggle('is-selected', player.id === state.selectedPlayerId);
  });
  if (dom.syncToPrimary) {
    dom.syncToPrimary.classList.toggle('btn-primary', !state.selectedPlayerId);
  }
}

function syncToPrimary() {
  const primary = getPrimaryPlayer();
  if (!primary?.video?.duration) return;
  const time = primary.video.currentTime || 0;
  state.selectedPlayerId = null;
  syncSelectedPlayerUI();
  state.players.forEach((player) => {
    if (!player.video.duration) return;
    player.video.currentTime = clamp(time, 0, player.video.duration);
    player.video.playbackRate = primary.video.playbackRate || 1;
  });
  updateGroupTimeline();
  updateGroupPlayButton();
}

function resolveUrl(path) {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  try {
    return new URL(path, state.apiBase).toString();
  } catch {
    return path;
  }
}

function loadAuth() {
  try {
    const raw = localStorage.getItem('platformAuth');
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed?.accessToken ? parsed : null;
  } catch {
    return null;
  }
}

async function apiFetch(path, { method = 'GET', body, headers = {}, _retry = false } = {}) {
  const opts = { method, headers: { ...headers } };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  if (state.auth?.accessToken) {
    opts.headers.Authorization = `Bearer ${state.auth.accessToken}`;
  }

  const res = await fetch(`${state.apiBase}${path}`, opts);
  if (res.status === 401 && state.auth?.refreshToken && !_retry) {
    const refreshed = await refreshToken();
    if (refreshed) return apiFetch(path, { method, body, headers, _retry: true });
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `请求失败：${res.status}`);
  }
  return res.status === 204 ? null : res.json();
}

async function refreshToken() {
  try {
    const res = await fetch(`${state.apiBase}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: state.auth.refreshToken }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    state.auth = {
      ...state.auth,
      accessToken: data.access_token,
      refreshToken: data.refresh_token || state.auth.refreshToken,
    };
    localStorage.setItem('platformAuth', JSON.stringify(state.auth));
    return true;
  } catch {
    return false;
  }
}

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '00:00.000';
  const minutes = Math.floor(seconds / 60);
  const wholeSeconds = Math.floor(seconds % 60);
  const millis = Math.floor((seconds % 1) * 1000);
  return `${String(minutes).padStart(2, '0')}:${String(wholeSeconds).padStart(2, '0')}.${String(millis).padStart(3, '0')}`;
}

function formatDateTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', { hour12: false });
}

function setStatus(message) {
  if (dom.status) dom.status.textContent = message || '';
}

function parseError(err) {
  if (!err) return '操作失败';
  try {
    const parsed = JSON.parse(err.message || '');
    return parsed.detail || err.message || '操作失败';
  } catch {
    return err.message || String(err);
  }
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
