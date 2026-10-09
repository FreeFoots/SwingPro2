const state = {
  // apiBase: window.__API_BASE__ || localStorage.getItem('platformApiBase') || 'http://127.0.0.1:8000',
  apiBase: window.__API_BASE__ || localStorage.getItem('platformApiBase') || window.location.origin,
  auth: loadAuth(),
  filters: { view: '', search: '', ownerId: null, ownerLabel: '', ownerKeyword: '', wechatKeyword: '', drawStatus: '', pairedStatus: '', dateStart: '', dateEnd: '' },
  pagination: { page: 1, limit: 60, total: 0 },
  videos: [],
  videosTotal: 0,
  management: {
    invites: [],
    users: [],
    usersIndex: [],
    userSearchSuggestions: [],
    ownerSuggestions: [],
    wechatSuggestions: [],
    systemChecks: [],
    systemAnomalies: [],
    systemCheckFilters: {
      status: 'all',
      keyword: '',
      anomalyCategory: 'all',
      anomalyKeyword: '',
    },
    activePanel: 'invites',
    inviteStatus: 'all',
    selectedUserId: null,
    statsDays: 7,
    portraitUsers: {
      high: [],
      medium: [],
      light: [],
      silent: [],
    },
  },
  profile: {
    data: null,
    phoneCooldown: 0,
    phoneTimer: null,
    passwordCooldown: 0,
    passwordTimer: null,
  },
  sync: {
    active: false,
    selected: new Set(),
  },
  userCache: new Map(),
  viewMode: 'home',
  mainPane: 'videos',
  previousPane: null,
};

const ROLE_PRIORITY = {
  user: 0,
  business: 1,
  admin: 2,
  super_admin: 3,
  system_admin: 4,
};

let userMenuHideTimer = null;
const toastStore = new Map();

const ROLE_LABELS = {
  user: '用户',
  business: '业务员',
  admin: '管理员',
  super_admin: '超级管理员',
  system_admin: '系统管理员',
};

const WEB_MIN_ROLE = 'admin';
const PASSWORD_PATTERN = /^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{8,16}$/;
const ANIMATION_DURATION = 260;

function isWebAllowed(role) {
  return roleAtLeast(role, WEB_MIN_ROLE);
}

let confirmResolver = null;
let inputResolver = null;
let inputDialogConfig = null;

function ensureAllowedRole() {
  const role = state.auth?.role || 'user';
  if (!isWebAllowed(role)) {
    alert('当前账号无权访问 Web 平台');
    logout();
    return false;
  }
  console.debug('[platform] role check passed', role);
  return true;
}

const LOGIN_URL = window.__LOGIN_URL__ || '/users/login/index.html';

function roleAtLeast(currentRole, requiredRole) {
  return (ROLE_PRIORITY[currentRole] ?? -1) >= (ROLE_PRIORITY[requiredRole] ?? 99);
}

function getRoleLabel(role) {
  return ROLE_LABELS[role] || role || '未知';
}

const dom = {};

const DEFAULT_AVATAR = `data:image/svg+xml;utf8,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" fill="none"><rect width="120" height="120" rx="24" fill="#e2e8f0"/><path d="M60 64c14.36 0 26-11.64 26-26S74.36 12 60 12 34 23.64 34 38s11.64 26 26 26Zm0 10c-20.46 0-38 11.22-38 25.08C22 109.94 22 112 22 112h76s0-2.06 0-12.92C98 85.22 80.46 74 60 74Z" fill="#94a3b8"/></svg>')}`;
let ownerSuggestTimer = null;
let wechatSuggestTimer = null;
let userSearchSuggestTimer = null;
let dateFilterTimer = null;
let portraitHoverHideTimer = null;
let portraitHoverActiveKey = null;
let portraitHoverActiveTrigger = null;
let systemCheckFilterTimer = null;

document.addEventListener('DOMContentLoaded', () => {
  window.__platformState = state;
  try {
    cacheDom();
    initFadePanes();
    initConfirmModal();
    initInputModal();
    if (!state.auth) {
      redirectToLogin();
      return;
    }
    if (!ensureAllowedRole()) return;

    // Load state from sessionStorage if available
    const savedState = sessionStorage.getItem('swingpro_platform_state');
    if (savedState) {
      try {
        const parsed = JSON.parse(savedState);
        if (parsed.filters) state.filters = parsed.filters;
        if (parsed.pagination) state.pagination = parsed.pagination;
      } catch (e) {}
      sessionStorage.removeItem('swingpro_platform_state');
    }

    bindMainTabs();
    initCategoryBar();
    initSearch();
    initUploadDrawer();
    initNavBar();
    initPlayerControls();
    initManagementPanel();
    initProfileCenter();
    initVideoSelection();
    initAdminFilters();
    setMainPane('videos');
    syncAuthState();
    syncAdminFilterInputs();
    loadVideos();
  } catch (err) {
    console.error('[platform] 初始化失败', err);
    alert('页面初始化失败，请刷新后重试或查看控制台日志。');
  }
});

function cacheDom() {
  dom.grid = document.getElementById('video-grid');
  dom.empty = document.getElementById('empty-state');
  dom.categoryBar = document.getElementById('category-bar');
  dom.gallerySection = document.getElementById('gallery-section');
  dom.mainTabs = document.getElementById('main-tabs');
  dom.mainTabButtons = dom.mainTabs ? Array.from(dom.mainTabs.querySelectorAll('[data-pane]')) : [];
  dom.paneVideos = document.getElementById('pane-videos');
  dom.paneManagement = document.getElementById('pane-management');
  dom.managementSection = document.getElementById('management-section');
  dom.managementTabButton = dom.mainTabs ? dom.mainTabs.querySelector('[data-pane="management"]') : null;
  dom.navUserLabel = document.getElementById('nav-user-label');
  dom.navUserDropdown = document.getElementById('nav-user-dropdown');
  dom.navUserMenu = document.getElementById('nav-user-menu');
  dom.navProfileBtn = document.getElementById('open-profile');
  dom.navAvatarBtn = document.getElementById('nav-avatar-btn');
  dom.navAvatarImg = document.getElementById('nav-avatar-img');
  dom.navLogout = document.getElementById('nav-logout');
  if (dom.navUserLabel) dom.navUserLabel.textContent = '--';
  if (dom.navAvatarImg) {
    dom.navAvatarImg.src = DEFAULT_AVATAR;
    dom.navAvatarImg.onerror = () => {
      dom.navAvatarImg.src = DEFAULT_AVATAR;
    };
  }
  dom.drawer = document.getElementById('upload-drawer');
  dom.drawerBackdrop = document.getElementById('drawer-backdrop');
  dom.openUpload = document.getElementById('open-upload');
  dom.uploadForm = document.getElementById('upload-form');
  dom.uploadError = document.getElementById('upload-error');
  dom.uploadSuccess = document.getElementById('upload-success');
  dom.playerBackdrop = document.getElementById('player-backdrop');
  dom.playerClose = document.getElementById('player-close');
  dom.playerVideo = document.getElementById('player-video');
  dom.playerTitle = document.getElementById('player-title');
  dom.manageTabs = document.getElementById('manage-tabs');
  dom.managePanels = document.querySelectorAll('.manage-panel');
  dom.roleChip = document.getElementById('role-chip');
  dom.inviteForm = document.getElementById('invite-form');
  dom.inviteDuration = document.getElementById('invite-duration');
  dom.inviteSuccess = document.getElementById('invite-success');
  dom.inviteError = document.getElementById('invite-error');
  dom.inviteFilters = document.getElementById('invite-filters');
  dom.inviteTableBody = document.querySelector('#invite-table tbody');
  dom.userSearchForm = document.getElementById('user-search-form');
  dom.userSearchInput = document.getElementById('user-search-input');
  dom.userSearchSuggestions = document.getElementById('user-search-suggestions');
  dom.userRoleFilter = document.getElementById('user-role-filter');
  dom.userSearchResults = document.getElementById('user-search-results');
  dom.userSearchError = document.getElementById('user-search-error');
  dom.userIndex = document.getElementById('user-index');
  dom.adminFilters = document.getElementById('admin-filters');
  dom.adminOwnerInput = document.getElementById('admin-owner-input');
  dom.adminWechatInput = document.getElementById('admin-wechat-input');
  dom.adminPairedStatus = document.getElementById('admin-paired-status-btn');
  dom.adminDateStart = document.getElementById('admin-date-start');
  dom.adminDateEnd = document.getElementById('admin-date-end');
  dom.adminFilterApply = document.getElementById('admin-filter-apply');
  dom.adminFilterReset = document.getElementById('admin-filter-reset');
  dom.adminOwnerChip = document.getElementById('admin-owner-chip');
  dom.adminOwnerChipLabel = document.getElementById('admin-owner-chip-label');
  dom.adminOwnerSuggestions = document.getElementById('admin-owner-suggestions');
  dom.adminWechatSuggestions = document.getElementById('admin-wechat-suggestions');
  dom.profileSection = document.getElementById('profile-section');

  // New Profile Elements
  dom.profileAvatarImg = document.getElementById('profile-avatar-img');
  dom.profileNickname = document.getElementById('profile-nickname');
  dom.profileRole = document.getElementById('profile-role');
  dom.profilePhone = document.getElementById('profile-phone');
  dom.profilePhoneEdit = document.getElementById('profile-phone-edit');
  dom.profilePasswordEdit = document.getElementById('profile-password-edit');
  dom.profileCreated = document.getElementById('profile-created');

  // Profile Forms (in modals)
  dom.profilePhoneForm = document.getElementById('profile-phone-form');
  dom.profilePasswordForm = document.getElementById('profile-password-form');

  dom.videoToolbar = document.getElementById('video-toolbar');
  dom.videoRefresh = document.getElementById('video-refresh');
  dom.videoSelectToggle = document.getElementById('video-select-toggle');
  dom.videoSelectAll = document.getElementById('video-select-all');
  dom.videoDownloadSelected = document.getElementById('video-download-selected');
  dom.videoDeleteSelected = document.getElementById('video-delete-selected');
  dom.videoSelectionInfo = document.getElementById('video-selection-info');
  dom.videoPagination = document.getElementById('video-pagination');
  dom.videoTotalCount = document.getElementById('video-total-count');
  dom.videoPrevPage = document.getElementById('video-prev-page');
  dom.videoNextPage = document.getElementById('video-next-page');
  dom.videoCurrentPage = document.getElementById('video-current-page');
  dom.toastContainer = document.getElementById('toast-container');
  dom.confirmBackdrop = document.getElementById('confirm-backdrop');
  dom.confirmTitle = document.getElementById('confirm-title');
  dom.confirmMessage = document.getElementById('confirm-message');
  dom.confirmCancel = document.getElementById('confirm-cancel');
  dom.confirmOk = document.getElementById('confirm-ok');
  dom.inputBackdrop = document.getElementById('input-backdrop');
  dom.inputTitle = document.getElementById('input-title');
  dom.inputMessage = document.getElementById('input-message');
  dom.inputLabel = document.getElementById('input-label');
  dom.inputFieldWrap = document.getElementById('input-field-wrap');
  dom.inputField = document.getElementById('input-field');
  dom.inputSelectWrap = document.getElementById('input-select-wrap');
  dom.inputSelectLabel = document.getElementById('input-select-label');
  dom.inputSelect = document.getElementById('input-select');
  dom.inputError = document.getElementById('input-error');
  dom.inputHint = document.getElementById('input-hint');
  dom.inputCancel = document.getElementById('input-cancel');
  dom.inputOk = document.getElementById('input-ok');

  // Stats
  dom.statUsers = document.getElementById('stat-users');
  dom.statVideos = document.getElementById('stat-videos');
  dom.statActiveUsers = document.getElementById('stat-active-users');
  dom.statTodayUsers = document.getElementById('stat-today-users');
  dom.statTodayVideos = document.getElementById('stat-today-videos');
  dom.statTodayOnline = document.getElementById('stat-today-online');
  dom.statTodayTopSummary = document.getElementById('stat-today-top-summary');
  dom.statsPeriodSwitch = document.getElementById('stats-period-switch');
  dom.statsPeriodButtons = dom.statsPeriodSwitch ? Array.from(dom.statsPeriodSwitch.querySelectorAll('[data-stats-days]')) : [];
  dom.uploadTrendChart = document.getElementById('upload-trend-chart');
  dom.uploadTrendLegend = document.getElementById('upload-trend-legend');
  dom.uploadTrendTooltip = document.getElementById('upload-trend-tooltip');
  dom.uploadTrendSection = document.getElementById('upload-trend-section');
  dom.uploadStatsSection = document.getElementById('upload-stats-section');
  dom.userPortraitSection = document.getElementById('user-portrait-section');
  dom.portraitHoverCard = document.getElementById('portrait-hover-card');
  dom.overviewCardHigh = document.getElementById('overview-card-high');
  dom.overviewCardMedium = document.getElementById('overview-card-medium');
  dom.overviewCardLight = document.getElementById('overview-card-light');
  dom.overviewCardSilent = document.getElementById('overview-card-silent');
  dom.overviewLayerHigh = document.getElementById('overview-layer-high');
  dom.overviewLayerMedium = document.getElementById('overview-layer-medium');
  dom.overviewLayerLight = document.getElementById('overview-layer-light');
  dom.overviewLayerSilent = document.getElementById('overview-layer-silent');
  dom.overviewUploadUsers7d = document.getElementById('overview-upload-users-7d');
  dom.overviewUploadTotal7d = document.getElementById('overview-upload-total-7d');
  dom.overviewUploadAvg7d = document.getElementById('overview-upload-avg-7d');
  dom.overviewUploadTotalToday = document.getElementById('overview-upload-total-today');
  dom.uploadUserTableBody = document.querySelector('#upload-user-table tbody');
  dom.btnRefreshActivities = document.getElementById('btn-refresh-activities');
  dom.activityTableBody = document.querySelector('#activity-table tbody');
  dom.activityCategoryFilter = document.getElementById('activity-category-filter');
  dom.btnRefreshSystemCheck = document.getElementById('btn-refresh-system-check');
  dom.systemCheckGeneratedAt = document.getElementById('system-check-generated-at');
  dom.systemCheckStatusFilter = document.getElementById('system-check-status-filter');
  dom.systemCheckKeyword = document.getElementById('system-check-keyword');
  dom.systemCheckTotal = document.getElementById('system-check-total');
  dom.systemCheckOk = document.getElementById('system-check-ok');
  dom.systemCheckWarn = document.getElementById('system-check-warn');
  dom.systemCheckError = document.getElementById('system-check-error');
  dom.systemAnomalyTotal = document.getElementById('system-anomaly-total');
  dom.systemAnomalyCategoryFilter = document.getElementById('system-anomaly-category-filter');
  dom.systemAnomalyKeyword = document.getElementById('system-anomaly-keyword');
  dom.systemAnomalyTip = document.getElementById('system-anomaly-tip');
  dom.systemCheckTableBody = document.querySelector('#system-check-table tbody');
  dom.systemAnomalyTableBody = document.querySelector('#system-anomaly-table tbody');
}

function initFadePanes() {
  document.querySelectorAll('.fade-pane').forEach((el) => {
    if (!el.hidden) {
      el.classList.add('pane-visible');
    }
  });
}

function initPlayerControls() {
  dom.playerClose?.addEventListener('click', (e) => {
    e.preventDefault();
    closePlayer();
  });
  dom.playerBackdrop?.addEventListener('click', (e) => {
    if (e.target === dom.playerBackdrop) {
      closePlayer();
    }
  });
}

function initConfirmModal() {
  if (!dom.confirmBackdrop) return;
  const settle = (value) => {
    if (confirmResolver) {
      confirmResolver(value);
      confirmResolver = null;
    }
    dom.confirmBackdrop.classList.remove('show');
    setTimeout(() => {
      if (!confirmResolver) dom.confirmBackdrop.hidden = true;
    }, 200);
  };
  dom.confirmCancel?.addEventListener('click', () => settle(false));
  dom.confirmOk?.addEventListener('click', () => settle(true));
  dom.confirmBackdrop.addEventListener('click', (e) => {
    if (e.target === dom.confirmBackdrop) {
      settle(false);
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !dom.confirmBackdrop.hidden) {
      settle(false);
    }
  });
}

function openConfirmDialog({ title = '提示', message = '确认执行操作吗？', confirmText = '确认', cancelText = '取消' } = {}) {
  if (!dom.confirmBackdrop) return Promise.resolve(true);
  if (confirmResolver) {
    confirmResolver(false);
    confirmResolver = null;
  }
  return new Promise((resolve) => {
    confirmResolver = resolve;
    if (dom.confirmTitle) dom.confirmTitle.textContent = title;
    if (dom.confirmMessage) dom.confirmMessage.textContent = message;
    if (dom.confirmOk) dom.confirmOk.textContent = confirmText;
    if (dom.confirmCancel) dom.confirmCancel.textContent = cancelText;
    dom.confirmBackdrop.hidden = false;
    requestAnimationFrame(() => dom.confirmBackdrop.classList.add('show'));
  });
}

function setInputDialogError(message = '') {
  if (!dom.inputError) return;
  const text = String(message || '').trim();
  dom.inputError.textContent = text;
  dom.inputError.hidden = !text;
}

function initInputModal() {
  if (!dom.inputBackdrop) return;

  const settle = (value) => {
    if (inputResolver) {
      inputResolver(value);
      inputResolver = null;
    }
    inputDialogConfig = null;
    dom.inputBackdrop.classList.remove('show');
    setTimeout(() => {
      if (!inputResolver) dom.inputBackdrop.hidden = true;
    }, 200);
  };

  const submit = () => {
    if (!inputDialogConfig) {
      settle(null);
      return;
    }

    const useSelect = inputDialogConfig.mode === 'select';
    const raw = useSelect ? (dom.inputSelect?.value ?? '') : (dom.inputField?.value ?? '');
    const value = String(raw ?? '').trim();
    const required = inputDialogConfig.required !== false;

    if (required && !value) {
      setInputDialogError(inputDialogConfig.requiredMessage || '请输入有效内容');
      return;
    }

    if (typeof inputDialogConfig.validate === 'function') {
      const result = inputDialogConfig.validate(value);
      if (result !== true) {
        setInputDialogError(typeof result === 'string' && result ? result : '输入内容不符合要求');
        return;
      }
    }

    settle(value);
  };

  dom.inputCancel?.addEventListener('click', () => settle(null));
  dom.inputOk?.addEventListener('click', submit);

  dom.inputBackdrop.addEventListener('click', (e) => {
    if (e.target === dom.inputBackdrop) {
      settle(null);
    }
  });

  document.addEventListener('keydown', (e) => {
    if (dom.inputBackdrop.hidden) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      settle(null);
      return;
    }
    if (e.key === 'Enter') {
      const active = document.activeElement;
      if (active === dom.inputField || active === dom.inputSelect || dom.inputBackdrop.contains(active)) {
        e.preventDefault();
        submit();
      }
    }
  });
}

function openInputDialog({
  mode = 'input',
  title = '请输入',
  message = '请填写以下内容',
  label = '',
  placeholder = '',
  defaultValue = '',
  inputType = 'text',
  confirmText = '确认',
  cancelText = '取消',
  hint = '',
  options = [],
  required = true,
  requiredMessage = '',
  validate = null,
} = {}) {
  if (!dom.inputBackdrop) return Promise.resolve(null);

  if (inputResolver) {
    inputResolver(null);
    inputResolver = null;
  }
  inputDialogConfig = {
    mode,
    required,
    requiredMessage,
    validate,
  };

  return new Promise((resolve) => {
    inputResolver = resolve;

    if (dom.inputTitle) dom.inputTitle.textContent = title;
    if (dom.inputMessage) dom.inputMessage.textContent = message || '';
    if (dom.inputOk) dom.inputOk.textContent = confirmText;
    if (dom.inputCancel) dom.inputCancel.textContent = cancelText;

    if (dom.inputHint) {
      dom.inputHint.textContent = hint || '';
      dom.inputHint.hidden = !hint;
    }
    setInputDialogError('');

    const useSelect = mode === 'select';
    if (dom.inputFieldWrap) dom.inputFieldWrap.hidden = useSelect;
    if (dom.inputSelectWrap) dom.inputSelectWrap.hidden = !useSelect;

    if (useSelect && dom.inputSelect) {
      const normalized = (Array.isArray(options) ? options : []).map((item) => {
        if (typeof item === 'string') {
          return { value: item, label: item, description: '' };
        }
        return {
          value: item?.value,
          label: item?.label ?? item?.value,
          description: item?.description || '',
        };
      }).filter((item) => item.value !== undefined && item.value !== null);

      dom.inputSelect.innerHTML = '';
      normalized.forEach((item) => {
        const opt = document.createElement('option');
        opt.value = String(item.value);
        opt.textContent = item.description ? `${item.label} (${item.description})` : String(item.label);
        dom.inputSelect.appendChild(opt);
      });
      const desired = String(defaultValue ?? '');
      if (desired && normalized.some((item) => String(item.value) === desired)) {
        dom.inputSelect.value = desired;
      } else if (normalized.length) {
        dom.inputSelect.value = String(normalized[0].value);
      }

      if (dom.inputSelectLabel) {
        dom.inputSelectLabel.textContent = label || '请选择';
        dom.inputSelectLabel.hidden = !label;
      }
    }

    if (!useSelect && dom.inputField) {
      const safeType = ['text', 'password', 'number', 'tel'].includes(inputType) ? inputType : 'text';
      dom.inputField.type = safeType;
      dom.inputField.placeholder = placeholder || '';
      dom.inputField.value = String(defaultValue ?? '');
      if (dom.inputLabel) {
        dom.inputLabel.textContent = label || '输入内容';
        dom.inputLabel.hidden = !label;
      }
    }

    dom.inputBackdrop.hidden = false;
    requestAnimationFrame(() => {
      dom.inputBackdrop.classList.add('show');
      if (useSelect && dom.inputSelect) {
        dom.inputSelect.focus();
      } else if (dom.inputField) {
        dom.inputField.focus();
        dom.inputField.select();
      }
    });
  });
}

function openSelectDialog(options = {}) {
  return openInputDialog({ ...options, mode: 'select' });
}

function bindMainTabs() {
  if (!dom.mainTabs) return;
  dom.mainTabs.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-pane]');
    if (!btn || btn.hidden) return;
    const pane = btn.dataset.pane || 'videos';
    if (state.viewMode === 'profile') {
      closeProfileSection(pane);
      return;
    }
    setMainPane(pane);
  });
}

function setMainPane(pane = 'videos') {
  const targetPane = pane || 'videos';
  const role = state.auth?.role || 'user';
  if (targetPane === 'management' && !roleAtLeast(role, 'admin')) {
    return;
  }
  if (state.viewMode === 'profile') {
    closeProfileSection(targetPane);
    return;
  }
  console.debug('[platform] switch main pane', { targetPane, role, profileView: state.viewMode });
  state.mainPane = targetPane;
  configureManagementVisibility();
  updateMainPaneVisibility();
}

function setAnimatedVisibility(element, shouldShow, className = 'pane-visible') {
  if (!element) return;
  if (shouldShow) {
    if (element.__hideTimer) {
      clearTimeout(element.__hideTimer);
      element.__hideTimer = null;
    }
    element.hidden = false;
    element.classList.remove(className);
    requestAnimationFrame(() => element.classList.add(className));
  } else {
    if (element.hidden) return;
    element.classList.remove(className);
    if (element.__hideTimer) {
      clearTimeout(element.__hideTimer);
    }
    element.__hideTimer = setTimeout(() => {
      element.hidden = true;
      element.__hideTimer = null;
    }, ANIMATION_DURATION);
  }
}

function updateMainPaneVisibility() {
  if (dom.mainTabButtons) {
    dom.mainTabButtons.forEach((btn) => {
      const pane = btn.dataset.pane;
      const isActive = state.viewMode !== 'profile' && pane === state.mainPane;
      btn.classList.toggle('active', isActive);
    });
  }
  const role = state.auth?.role || 'user';
  const profileOpen = state.viewMode === 'profile';
  const showVideos = !profileOpen && state.mainPane === 'videos';
  const showManagement = !profileOpen && state.mainPane === 'management' && roleAtLeast(role, 'admin');
  console.debug('[platform] update panes', { showVideos, showManagement, profileOpen });
  if (!showVideos && state.sync.active) {
    state.sync.active = false;
    state.sync.selected.clear();
    updateVideoSelectionUI();
  }
  setAnimatedVisibility(dom.paneVideos, showVideos);
  setAnimatedVisibility(dom.gallerySection, showVideos);
  setAnimatedVisibility(dom.categoryBar, showVideos);
  setAnimatedVisibility(dom.paneManagement, showManagement);
  setAnimatedVisibility(dom.managementSection, showManagement);
  updateAdminFiltersVisibility();
}

function initManagementPanel() {
  reorderOverviewSections();

  dom.manageTabs?.addEventListener('click', (e) => {
    const btn = e.target.closest('.manage-tab');
    if (!btn || btn.hidden) return;
    activateManagementPanel(btn.dataset.panel);
  });

  dom.inviteForm?.addEventListener('submit', handleInviteSubmit);
  dom.userSearchForm?.addEventListener('submit', handleUserSearch);
  dom.userSearchInput?.addEventListener('input', handleUserSearchInputChanged);
  dom.userSearchInput?.addEventListener('focus', handleUserSearchInputChanged);
  dom.userSearchInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      hideUserSearchSuggestions();
    }
  });
  dom.userSearchSuggestions?.addEventListener('click', handleUserSearchSuggestionClick);
  dom.userRoleFilter?.addEventListener('change', () => {
    if (dom.userSearchInput?.value?.trim()) {
      handleUserSearchInputChanged();
    }
  });
  dom.userIndex?.addEventListener('click', handleUserIndexClick);
  dom.userIndex?.addEventListener('keydown', handleUserIndexKeydown);
  dom.userSearchResults?.addEventListener('click', handleUserResultAction);
  dom.inviteFilters?.addEventListener('click', (e) => {
    const btn = e.target.closest('.manage-subtab');
    if (!btn || btn.classList.contains('active')) return;
    const status = btn.dataset.status || 'all';
    state.management.inviteStatus = status;
    dom.inviteFilters.querySelectorAll('.manage-subtab').forEach((el) => el.classList.toggle('active', el === btn));
    loadInvites();
  });

  dom.statsPeriodSwitch?.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-stats-days]');
    if (!btn) return;
    const days = Number(btn.dataset.statsDays || 7);
    if (![7, 15, 30].includes(days)) return;
    if (state.management.statsDays === days) return;
    state.management.statsDays = days;
    updateStatsPeriodButtons();
    loadSystemStats();
  });

  dom.uploadUserTableBody?.addEventListener('click', handleUploadUserRowClick);
  initPortraitHoverCard();

  dom.btnRefreshSystemCheck?.addEventListener('click', loadSystemChecks);
  dom.systemCheckStatusFilter?.addEventListener('change', handleSystemCheckFilterChanged);
  dom.systemCheckKeyword?.addEventListener('input', handleSystemCheckFilterChanged);
  dom.systemAnomalyCategoryFilter?.addEventListener('change', handleSystemCheckFilterChanged);
  dom.systemAnomalyKeyword?.addEventListener('input', handleSystemCheckFilterChanged);
}

function reorderOverviewSections() {
  const panel = document.getElementById('panel-stats');
  if (!panel || !dom.userPortraitSection || !dom.uploadTrendSection || !dom.uploadStatsSection) return;
  const ref = dom.userPortraitSection;
  panel.insertBefore(ref, dom.uploadTrendSection);
  panel.insertBefore(dom.uploadTrendSection, dom.uploadStatsSection);
}

function activateManagementPanel(panelName) {
  if (!dom.manageTabs) return;
  hidePortraitHoverCard();
  const buttons = Array.from(dom.manageTabs.querySelectorAll('.manage-tab')).filter((btn) => !btn.hidden);
  if (!buttons.length) return;
  let target = panelName;
  if (!target || !buttons.some((btn) => btn.dataset.panel === target)) {
    target = buttons[0].dataset.panel;
  }
  buttons.forEach((btn) => {
    const isActive = btn.dataset.panel === target;
    btn.classList.toggle('active', isActive);
  });
  document.querySelectorAll('.manage-panel').forEach((panel) => {
    const isActive = panel.id === `panel-${target}`;
    panel.classList.toggle('active', isActive);
    setAnimatedVisibility(panel, isActive);
  });
  state.management.activePanel = target;
  if (target === 'invites' && roleAtLeast(state.auth?.role, 'admin')) {
    loadInvites();
  } else if (target === 'roles' && roleAtLeast(state.auth?.role, 'admin')) {
    loadRoleIndex();
  } else if (target === 'stats' && roleAtLeast(state.auth?.role, 'admin')) {
    loadSystemStats();
  } else if (target === 'system-check' && roleAtLeast(state.auth?.role, 'system_admin')) {
    loadSystemChecks();
  }
}

function configureManagementVisibility() {
  if (!dom.managementSection) return;
  const role = state.auth?.role || 'user';
  if (dom.roleChip) {
    dom.roleChip.textContent = `当前角色：${getRoleLabel(role)}`;
  }

  const canManage = roleAtLeast(role, 'admin');
  const videoTab = dom.mainTabs ? dom.mainTabs.querySelector('[data-pane="videos"]') : null;
  const manageTab = dom.mainTabs ? dom.mainTabs.querySelector('[data-pane="management"]') : null;
  if (videoTab) videoTab.hidden = false;
  if (manageTab) manageTab.hidden = !canManage;
  if (dom.openUpload) dom.openUpload.hidden = false;
  if (dom.managementTabButton) {
    dom.managementTabButton.hidden = !canManage;
  }
  if (!canManage) {
    if (state.mainPane === 'management') {
      state.mainPane = 'videos';
      updateMainPaneVisibility();
    } else {
      updateMainPaneVisibility();
    }
    return;
  }
  const buttons = dom.manageTabs ? Array.from(dom.manageTabs.querySelectorAll('.manage-tab')) : [];
  let firstVisible = null;
  buttons.forEach((btn) => {
    const panelName = btn.dataset.panel;
    const required = btn.dataset.minRole || 'admin';
    const visible = roleAtLeast(role, required);
    btn.hidden = !visible;
    const panel = document.getElementById(`panel-${btn.dataset.panel}`);
    if (panel) {
      if (!visible) {
        panel.classList.remove('pane-visible');
        panel.hidden = true;
      }
    }
    if (visible && !firstVisible) {
      firstVisible = btn.dataset.panel;
    }
  });

  if (!firstVisible) {
    setAnimatedVisibility(dom.managementSection, false);
    return;
  }

  const shouldShowSection = state.viewMode !== 'profile' && state.mainPane === 'management';
  setAnimatedVisibility(dom.managementSection, shouldShowSection);

  const desiredPanel = state.management.activePanel;
  const desiredPanelVisible = desiredPanel && !document.getElementById(`panel-${desiredPanel}`)?.hidden;
  activateManagementPanel(desiredPanelVisible ? desiredPanel : firstVisible);

  if (state.mainPane === 'management') {
    if (roleAtLeast(role, 'admin')) {
      loadRoleIndex();
      loadInvites();
    }
  }
}

function initAdminFilters() {
  if (!dom.adminFilters) return;
  dom.adminFilterApply?.addEventListener('click', () => {
    state.pagination.page = 1; // Reset page on filter apply
    applyAdminOwnerFilter();
  });
  dom.adminFilterReset?.addEventListener('click', resetAdminOwnerFilter);
  dom.adminOwnerChip?.addEventListener('click', (e) => {
    if (e.target.closest('[data-action="clear-owner"]')) {
      resetAdminOwnerFilter();
    }
  });
  dom.adminOwnerInput?.addEventListener('input', handleOwnerInputChanged);
  dom.adminOwnerInput?.addEventListener('focus', handleOwnerInputChanged);
  dom.adminWechatInput?.addEventListener('input', handleWechatInputChanged);
  dom.adminWechatInput?.addEventListener('focus', handleWechatInputChanged);
  dom.adminPairedStatus?.addEventListener('click', () => {
    const btn = dom.adminPairedStatus;
    if (btn.dataset.status === 'paired') {
      btn.dataset.status = '';
      btn.classList.remove('btn-primary');
      btn.classList.add('btn-secondary');
    } else {
      btn.dataset.status = 'paired';
      btn.classList.remove('btn-secondary');
      btn.classList.add('btn-primary');
    }
    state.pagination.page = 1;
    applyAdminOwnerFilter();
  });
  dom.adminOwnerInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      state.pagination.page = 1;
      applyAdminOwnerFilter();
    }
  });
  dom.adminWechatInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      state.pagination.page = 1;
      applyAdminOwnerFilter();
    }
  });
  dom.adminOwnerSuggestions?.addEventListener('click', handleOwnerSuggestionClick);
  dom.adminWechatSuggestions?.addEventListener('click', handleWechatSuggestionClick);
  document.addEventListener('click', handleSuggestionBlur);
  dom.adminDateStart?.addEventListener('change', handleAdminDateChange);
  dom.adminDateEnd?.addEventListener('change', handleAdminDateChange);
  updateAdminFiltersVisibility();
  updateAdminOwnerChip();
}

function updateAdminFiltersVisibility() {
  if (!dom.adminFilters) return;
  const canFilter = state.auth && roleAtLeast(state.auth.role, 'admin');
  if (!canFilter) {
    setAnimatedVisibility(dom.adminFilters, false);
    state.filters.ownerId = null;
    state.filters.ownerLabel = '';
    state.filters.ownerKeyword = '';
    state.filters.wechatKeyword = '';
    state.filters.drawStatus = '';
    state.filters.pairedStatus = '';
    state.filters.dateStart = '';
    state.filters.dateEnd = '';
    hideOwnerSuggestions();
    hideWechatSuggestions();
    syncAdminFilterInputs();
    updateAdminOwnerChip();
    return;
  }
  const shouldShowFilters = state.viewMode !== 'profile' && state.mainPane === 'videos';
  setAnimatedVisibility(dom.adminFilters, shouldShowFilters);
  if (shouldShowFilters) {
    syncAdminFilterInputs();
  }
  updateAdminOwnerChip();
}

async function applyAdminOwnerFilter() {
  if (!state.auth || !roleAtLeast(state.auth.role, 'admin')) return;
  const ownerKeyword = dom.adminOwnerInput?.value.trim() || '';
  const wechatKeyword = dom.adminWechatInput?.value.trim() || '';
  const pairedStatus = dom.adminPairedStatus?.dataset.status || '';
  const start = dom.adminDateStart?.value || '';
  const end = dom.adminDateEnd?.value || '';

  if (start && end && start > end) {
    spawnToast('起始日期不能晚于终止日期', 'warning');
    return;
  }

  state.filters.dateStart = start;
  state.filters.dateEnd = end;

  state.filters.ownerKeyword = ownerKeyword;
  state.filters.wechatKeyword = wechatKeyword;
  state.filters.drawStatus = '';
  state.filters.pairedStatus = pairedStatus;

  if (ownerKeyword) {
    const selectedMismatch = !state.filters.ownerLabel || state.filters.ownerLabel !== ownerKeyword;
    if (!state.filters.ownerId || selectedMismatch) {
      try {
        const data = await apiFetch(`/users?q=${encodeURIComponent(ownerKeyword)}&limit=1`);
        if (data?.items?.length) {
          const user = data.items[0];
          state.filters.ownerId = user.id;
          state.filters.ownerLabel = user.username || maskTelephone(user.telephone) || user.id.slice(0, 8);
        } else {
          spawnToast('未找到匹配的账号', 'warning');
          return;
        }
      } catch (e) {
        console.warn(e);
      }
    }
  } else {
    state.filters.ownerId = null;
    state.filters.ownerLabel = '';
  }

  syncAdminFilterInputs();
  updateAdminOwnerChip();
  hideOwnerSuggestions();
  hideWechatSuggestions();
  state.pagination.page = 1;
  await loadVideos();
}

function syncAdminFilterInputs() {
  if (dom.adminOwnerInput && document.activeElement !== dom.adminOwnerInput) {
    dom.adminOwnerInput.value = state.filters.ownerKeyword || state.filters.ownerLabel || '';
  }
  if (dom.adminWechatInput && document.activeElement !== dom.adminWechatInput) {
    dom.adminWechatInput.value = state.filters.wechatKeyword || '';
  }
  if (dom.adminPairedStatus) {
    const setPaired = state.filters.pairedStatus === 'paired';
    dom.adminPairedStatus.dataset.status = setPaired ? 'paired' : '';
    dom.adminPairedStatus.textContent = '仅查看配对视频';
    if (setPaired) {
      dom.adminPairedStatus.classList.remove('btn-secondary');
      dom.adminPairedStatus.classList.add('btn-primary');
    } else {
      dom.adminPairedStatus.classList.remove('btn-primary');
      dom.adminPairedStatus.classList.add('btn-secondary');
    }
  }
  if (dom.adminDateStart && document.activeElement !== dom.adminDateStart) {
    dom.adminDateStart.value = state.filters.dateStart || '';
  }
  if (dom.adminDateEnd && document.activeElement !== dom.adminDateEnd) {
    dom.adminDateEnd.value = state.filters.dateEnd || '';
  }
}

async function resetAdminOwnerFilter() {
  state.filters.ownerId = null;
  state.filters.ownerLabel = '';
  state.filters.ownerKeyword = '';
  state.filters.wechatKeyword = '';
  state.filters.drawStatus = '';
  state.filters.pairedStatus = '';
  state.filters.dateStart = '';
  state.filters.dateEnd = '';

  if (dom.adminOwnerInput) {
    dom.adminOwnerInput.value = '';
  }
  if (dom.adminWechatInput) dom.adminWechatInput.value = '';
  if (dom.adminPairedStatus) {
    dom.adminPairedStatus.dataset.status = '';
    dom.adminPairedStatus.classList.remove('btn-primary');
    dom.adminPairedStatus.classList.add('btn-secondary');
  }
  if (dom.adminDateStart) dom.adminDateStart.value = '';
  if (dom.adminDateEnd) dom.adminDateEnd.value = '';

  hideOwnerSuggestions();
  hideWechatSuggestions();
  syncAdminFilterInputs();
  updateAdminOwnerChip();
  if (state.auth && roleAtLeast(state.auth.role, 'admin')) {
    state.pagination.page = 1;
    await loadVideos();
  }
}

function updateAdminOwnerChip() {
  if (!dom.adminOwnerChip) return;
  const hasOwner = !!state.filters.ownerId;
  const hasWechat = !!state.filters.wechatKeyword;
  const hasPairedStatus = !!state.filters.pairedStatus;
  const hasDate = !!state.filters.dateStart || !!state.filters.dateEnd;
  const hasFilter = hasOwner || hasWechat || hasPairedStatus || hasDate;

  dom.adminOwnerChip.hidden = !hasFilter;
  if (hasFilter && dom.adminOwnerChipLabel) {
    const parts = [];
    if (hasOwner) {
      parts.push(`账号：${state.filters.ownerLabel || '未知账号'}`);
    }
    if (hasWechat) {
        parts.push(`微信：${state.filters.wechatKeyword}`);
    }
    if (hasPairedStatus) {
      parts.push('配对：配对视频');
    }
    if (hasDate) {
      const from = state.filters.dateStart || '不限';
      const to = state.filters.dateEnd || '不限';
      parts.push(`时间：${from} ~ ${to}`);
    }
    dom.adminOwnerChipLabel.textContent = parts.join('；');
  }
}

function handleOwnerInputChanged() {
  if (!dom.adminOwnerInput || !roleAtLeast(state.auth?.role, 'admin')) return;
  const keyword = dom.adminOwnerInput.value.trim();
  state.filters.ownerKeyword = keyword;
  if (!keyword || (state.filters.ownerLabel && keyword !== state.filters.ownerLabel)) {
    state.filters.ownerId = null;
    state.filters.ownerLabel = '';
  }
  updateAdminOwnerChip();
  if (ownerSuggestTimer) clearTimeout(ownerSuggestTimer);
  if (!keyword) {
    fetchOwnerSuggestions('');
    return;
  }

  ownerSuggestTimer = setTimeout(() => fetchOwnerSuggestions(keyword), 250);
}

function handleWechatInputChanged() {
  if (!dom.adminWechatInput || !roleAtLeast(state.auth?.role, 'admin')) return;
  const keyword = dom.adminWechatInput.value.trim();
  state.filters.wechatKeyword = keyword;
  updateAdminOwnerChip();
  if (wechatSuggestTimer) clearTimeout(wechatSuggestTimer);
  if (!keyword) {
    fetchWechatSuggestions('');
    return;
  }

  wechatSuggestTimer = setTimeout(() => fetchWechatSuggestions(keyword), 250);
}

async function fetchOwnerSuggestions(keyword = '') {
  try {
    const limit = keyword ? 8 : 200;
    const res = await apiFetch(`/users?q=${encodeURIComponent(keyword)}&limit=${limit}`);
    const items = res?.items || [];
    state.management.usersIndex = items; // Cache for reference
    state.management.ownerSuggestions = items;
    renderOwnerSuggestions();
  } catch (err) {
    console.warn('[platform] fetch owner suggestions failed', err);
    state.management.ownerSuggestions = [];
    hideOwnerSuggestions();
  }
}

function renderOwnerSuggestions() {
  if (!dom.adminOwnerSuggestions) return;
  const items = state.management.ownerSuggestions || [];
  if (!items.length) {
    hideOwnerSuggestions();
    return;
  }

  dom.adminOwnerSuggestions.innerHTML = items
    .map((item) => {
      const name = item.username || maskTelephone(item.telephone) || item.telephone || item.id.slice(0, 8);
      const phone = item.telephone || '';
      const avatar = item.avatar_url || DEFAULT_AVATAR;
      return `
        <button type="button" data-id="${item.id}" data-name="${escapeHtml(name)}" data-phone="${escapeHtml(item.telephone || '')}" data-type="user">
          <span class="suggestion-main">
            <img class="suggestion-avatar" src="${escapeHtml(avatar)}" alt="${escapeHtml(name)}" onerror="this.src='${DEFAULT_AVATAR}'" />
            <span class="suggestion-name">${escapeHtml(name)}</span>
          </span>
          ${phone ? `<span class="suggestion-meta">${escapeHtml(phone)}</span>` : ''}
        </button>
      `;
    })
    .join('');
  dom.adminOwnerSuggestions.hidden = false;
}

function hideOwnerSuggestions() {
  if (!dom.adminOwnerSuggestions) return;
  dom.adminOwnerSuggestions.hidden = true;
  dom.adminOwnerSuggestions.innerHTML = '';
}

async function fetchWechatSuggestions(keyword = '') {
  try {
    const limit = keyword ? 8 : 500;
    const list = await apiFetch(`/players/search?q=${encodeURIComponent(keyword)}&limit=${limit}`);
    const playerItems = (Array.isArray(list) ? list : []).map((item) => ({
      name: item?.name || '未知微信用户',
      unionid: item?.wechat_unionid || '',
      avatar_url: item?.avatar_url || DEFAULT_AVATAR,
    }));
    const normalizedKeyword = keyword.trim().toLowerCase();
    const showGuest = !normalizedKeyword || '游客'.includes(keyword.trim()) || 'guest'.includes(normalizedKeyword);
    const items = showGuest
      ? [{ name: '游客', unionid: '', avatar_url: DEFAULT_AVATAR, is_guest: true }, ...playerItems]
      : playerItems;
    state.management.wechatSuggestions = items;
    renderWechatSuggestions();
  } catch (err) {
    console.warn('[platform] fetch wechat suggestions failed', err);
    state.management.wechatSuggestions = [];
    hideWechatSuggestions();
  }
}

function renderWechatSuggestions() {
  if (!dom.adminWechatSuggestions) return;
  const items = state.management.wechatSuggestions || [];
  if (!items.length) {
    hideWechatSuggestions();
    return;
  }

  dom.adminWechatSuggestions.innerHTML = items
    .map((item) => {
      const name = item.name || '未知微信用户';
      const unionid = item.unionid || '';
      const avatar = item.avatar_url || DEFAULT_AVATAR;
      return `
        <button type="button" data-name="${escapeHtml(name)}" data-unionid="${escapeHtml(unionid)}">
          <span class="suggestion-main">
            <img class="suggestion-avatar" src="${escapeHtml(avatar)}" alt="${escapeHtml(name)}" onerror="this.src='${DEFAULT_AVATAR}'" />
            <span class="suggestion-name">${escapeHtml(name)}</span>
          </span>
        </button>
      `;
    })
    .join('');
  dom.adminWechatSuggestions.hidden = false;
}

function hideWechatSuggestions() {
  if (!dom.adminWechatSuggestions) return;
  dom.adminWechatSuggestions.hidden = true;
  dom.adminWechatSuggestions.innerHTML = '';
}

function handleOwnerSuggestionClick(e) {
  const btn = e.target.closest('button');
  if (!btn) return;

  const id = btn.dataset.id;
  const label = btn.dataset.name;
  state.filters.ownerId = id;
  state.filters.ownerLabel = label;
  state.filters.ownerKeyword = label;
  if (dom.adminOwnerInput) dom.adminOwnerInput.value = label;

  hideOwnerSuggestions();
  updateAdminOwnerChip();
  state.pagination.page = 1;
  applyAdminOwnerFilter();
}

function handleWechatSuggestionClick(e) {
  const btn = e.target.closest('button');
  if (!btn) return;

  const keyword = btn.dataset.name || '';
  state.filters.wechatKeyword = keyword;
  if (dom.adminWechatInput) dom.adminWechatInput.value = keyword;

  hideWechatSuggestions();
  updateAdminOwnerChip();
  state.pagination.page = 1;
  loadVideos();
}

function handleSuggestionBlur(e) {
  const inOwner =
    (dom.adminOwnerInput && dom.adminOwnerInput.contains(e.target)) ||
    (dom.adminOwnerSuggestions && dom.adminOwnerSuggestions.contains(e.target));
  if (!inOwner) {
    hideOwnerSuggestions();
  }

  const inWechat =
    (dom.adminWechatInput && dom.adminWechatInput.contains(e.target)) ||
    (dom.adminWechatSuggestions && dom.adminWechatSuggestions.contains(e.target));
  if (!inWechat) {
    hideWechatSuggestions();
  }

  const inUserSearch =
    (dom.userSearchInput && dom.userSearchInput.contains(e.target)) ||
    (dom.userSearchSuggestions && dom.userSearchSuggestions.contains(e.target));
  if (!inUserSearch) {
    hideUserSearchSuggestions();
  }
}

function handleAdminDateChange() {
  scheduleDateFilterApply();
}

function scheduleDateFilterApply() {
  if (dateFilterTimer) {
    clearTimeout(dateFilterTimer);
  }
  dateFilterTimer = setTimeout(() => {
    applyAdminOwnerFilter();
  }, 150);
}

function getAlertTone(el) {
  if (!el || !el.classList) return 'info';
  if (el.classList.contains('alert-error')) return 'error';
  if (el.classList.contains('alert-success')) return 'success';
  if (el.classList.contains('alert-warning')) return 'warning';
  return 'info';
}

function spawnToast(message, tone = 'info', options = {}) {
  const { key } = options || {};
  const text = message || (tone === 'error' ? '操作失败，请稍后重试' : '操作已完成');
  if (!dom.toastContainer) {
    window.alert(text);
    return;
  }
  if (key && toastStore.has(key)) {
    dismissToast(toastStore.get(key));
  }
  const toast = document.createElement('div');
  toast.className = `toast toast-${tone}`;
  toast.setAttribute('role', 'alert');
  if (key) toast.dataset.key = key;
  const content = document.createElement('div');
  content.className = 'toast-message';
  content.textContent = text;
  toast.appendChild(content);
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'toast-close';
  close.setAttribute('aria-label', '关闭通知');
  close.textContent = '×';
  close.addEventListener('click', () => dismissToast(toast));
  toast.appendChild(close);
  dom.toastContainer.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('show'));
  const duration = tone === 'error' ? 5200 : tone === 'warning' ? 4500 : 3400;
  const timer = window.setTimeout(() => dismissToast(toast), duration);
  toast.dataset.timer = String(timer);
  if (key) toastStore.set(key, toast);
}

function dismissToast(toast, allowStoreRemoval = true) {
  if (!toast) return;
  const timer = Number(toast.dataset.timer);
  if (timer) {
    clearTimeout(timer);
  }
  const key = toast.dataset ? toast.dataset.key : '';
  if (allowStoreRemoval && key) {
    toastStore.delete(key);
  }
  toast.classList.remove('show');
  const remove = () => toast.remove();
  toast.addEventListener('transitionend', remove, { once: true });
  setTimeout(remove, 300);
}

function showAlert(el, message, options) {
  const tone = getAlertTone(el);
  if (el) {
    el.textContent = message ?? '';
    el.hidden = true;
  }
  const text = message ? String(message) : '';
  spawnToast(text, tone, options);
}

function hideAlert(...elements) {
  elements.forEach((el) => {
    if (el) el.hidden = true;
  });
}

function parseError(err) {
  if (!err) return '操作失败，请稍后重试';
  const message = err.message || String(err);
  try {
    const parsed = JSON.parse(message);
    if (typeof parsed === 'string') return parsed;
    if (parsed?.detail) {
      return typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail);
    }
  } catch (_) {
    // ignore
  }
  return message || '操作失败，请稍后重试';
}

function isPasswordValid(pwd) {
  return PASSWORD_PATTERN.test(pwd || '');
}

function parseDurationDays(value) {
  if (value === null || value === undefined) return null;
  const raw = String(value).trim();
  if (!raw) return null;
  const days = Number(raw);
  if (!Number.isInteger(days) || days <= 0) return null;
  return days;
}

function formatInviteStatus(status) {
  switch (status) {
    case 'unused':
      return '未使用';
    case 'used':
      return '已使用';
    case 'expired':
      return '已过期';
    default:
      return status || '未知';
  }
}

async function loadInvites() {
  if (!state.auth || !roleAtLeast(state.auth.role, 'admin')) return;
  hideAlert(dom.inviteError, dom.inviteSuccess);
  try {
    const status = state.management.inviteStatus || 'all';
    const params = new URLSearchParams({
      status,
      limit: '200',
    });
    const res = await apiFetch(`/invites?${params.toString()}`);
    state.management.invites = Array.isArray(res?.items) ? res.items : [];
    renderInviteTable();
  } catch (err) {
    showAlert(dom.inviteError, parseError(err));
  }
}

async function promptDurationDays(defaultDays = 30, title = '请输入生效天数') {
  const raw = await openInputDialog({
    title,
    message: '请输入正整数天数',
    label: '天数',
    placeholder: '例如 30',
    defaultValue: String(defaultDays),
    inputType: 'number',
    confirmText: '确认',
    cancelText: '取消',
    required: true,
    requiredMessage: '请输入有效的生效天数（正整数）',
    validate: (value) => (parseDurationDays(value) ? true : '请输入有效的生效天数（正整数）'),
  });
  if (raw === null) return null;
  return parseDurationDays(raw);
}

async function handleInviteSubmit(event) {
  event.preventDefault();
  hideAlert(dom.inviteError, dom.inviteSuccess);
  try {
    const payload = {};
    const durationDays = parseDurationDays(dom.inviteDuration?.value);
    if (dom.inviteDuration && dom.inviteDuration.value && durationDays === null) {
      spawnToast('请输入有效的生效天数（正整数）', 'warning');
      return;
    }
    if (durationDays) payload.duration_days = durationDays;
    const res = await apiFetch('/invites/create', { method: 'POST', body: payload });
    showAlert(dom.inviteSuccess, `邀请码已生成：${res.code}`);
    await loadInvites();
  } catch (err) {
    showAlert(dom.inviteError, parseError(err));
  }
}

function renderInviteTable() {
  if (!dom.inviteTableBody) return;
  dom.inviteTableBody.innerHTML = '';
  if (!state.management.invites.length) {
    const emptyRow = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.textContent = '暂无邀请码记录';
    td.style.color = '#94a3b8';
    td.style.textAlign = 'center';
    emptyRow.appendChild(td);
    dom.inviteTableBody.appendChild(emptyRow);
    return;
  }

  const statusOrder = {
    unused: 0,
    used: 1,
    expired: 2,
  };
  const sortedInvites = [...state.management.invites].sort((a, b) => {
    const sa = statusOrder[a?.status] ?? 99;
    const sb = statusOrder[b?.status] ?? 99;
    if (sa !== sb) return sa - sb;
    const ta = a?.created_at ? new Date(a.created_at).getTime() : 0;
    const tb = b?.created_at ? new Date(b.created_at).getTime() : 0;
    return tb - ta;
  });

  const fragment = document.createDocumentFragment();
  sortedInvites.forEach((invite) => {
    const tr = document.createElement('tr');
    const statusLabel = formatInviteStatus(invite.status);
    const telephone = invite.telephone || '未注册';
    const createdAt = invite.created_at ? formatDateTime(invite.created_at) : '—';
    const duration = invite.duration_days ? `${invite.duration_days}天` : '—';

    [invite.code, statusLabel, telephone, duration, createdAt].forEach((text) => {
      const td = document.createElement('td');
      td.textContent = text;
      tr.appendChild(td);
    });
    fragment.appendChild(tr);
  });
  dom.inviteTableBody.appendChild(fragment);
}

function initVideoSelection() {
  if (!dom.videoSelectToggle) return;
  if (!(state.sync.selected instanceof Set)) {
    state.sync.selected = new Set();
  }
  dom.videoRefresh?.addEventListener('click', () => {
    loadVideos();
  });
  dom.videoSelectToggle.addEventListener('click', toggleSelectionMode);
  dom.videoSelectAll?.addEventListener('click', handleSelectAll);
  dom.videoDownloadSelected?.addEventListener('click', downloadSelectedVideos);
  dom.videoDeleteSelected?.addEventListener('click', deleteSelectedVideos);
  updateVideoSelectionUI();
}

function toggleSelectionMode() {
  if (isDeletedView()) return;
  state.sync.active = !state.sync.active;
  state.sync.selected.clear();
  updateVideoSelectionUI();
}

function updateVideoSelectionUI() {
  const deletedView = isDeletedView();
  if (deletedView && state.sync.active) {
    state.sync.active = false;
    state.sync.selected.clear();
  }
  const active = !!state.sync.active;
  if (dom.videoSelectToggle) {
    dom.videoSelectToggle.textContent = deletedView ? '仅查看' : (active ? '取消' : '选择');
    dom.videoSelectToggle.disabled = deletedView;
  }
  if (dom.videoSelectAll) dom.videoSelectAll.hidden = !active;
  if (dom.videoDownloadSelected) {
    dom.videoDownloadSelected.hidden = !active;
    dom.videoDownloadSelected.disabled = state.sync.selected.size === 0;
  }
  if (dom.videoDeleteSelected) {
    dom.videoDeleteSelected.hidden = !active;
    dom.videoDeleteSelected.disabled = state.sync.selected.size === 0;
  }
  if (dom.videoSelectionInfo) {
    dom.videoSelectionInfo.hidden = !active;
    if (active) dom.videoSelectionInfo.textContent = `已选择 ${state.sync.selected.size} 个视频`;
  }
  if (dom.grid) dom.grid.classList.toggle('selecting', active);
  renderVideos();
}

function toggleVideoSelection(video, card) {
  const selection = state.sync.selected;
  if (selection.has(video.id)) {
    selection.delete(video.id);
  } else {
    selection.add(video.id);
  }
  if (card) {
    card.classList.toggle('selected', selection.has(video.id));
    const indicator = card.querySelector('.card-select-indicator');
    if (indicator) indicator.textContent = selection.has(video.id) ? '✓' : '';
  }
  if (dom.videoSelectionInfo) {
    dom.videoSelectionInfo.textContent = `已选择 ${selection.size} 个视频`;
  }
  if (dom.videoDeleteSelected) {
    dom.videoDeleteSelected.disabled = selection.size === 0;
  }
  if (dom.videoDownloadSelected) {
    dom.videoDownloadSelected.disabled = selection.size === 0;
  }
}

function handleSelectAll() {
  if (!state.sync.active) return;
  const selection = state.sync.selected;
  const currentPageIds = state.videos.map((video) => video.id);
  const selectedOnPage = currentPageIds.filter((id) => selection.has(id)).length;
  const allCurrentSelected = currentPageIds.length > 0 && selectedOnPage === currentPageIds.length;
  if (allCurrentSelected) {
    currentPageIds.forEach((id) => selection.delete(id));
  } else {
    currentPageIds.forEach((id) => selection.add(id));
  }
  updateVideoSelectionUI();
}

function triggerDownloadByUrl(url) {
  if (!url) return;
  const a = document.createElement('a');
  a.href = url;
  a.target = '_blank';
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

async function downloadSelectedVideos() {
  if (!state.sync.active || !state.sync.selected.size) return;
  const ids = Array.from(state.sync.selected);
  const ok = await openConfirmDialog({
    title: '批量下载',
    message: `确认打包下载选中的 ${ids.length} 个视频吗？`,
    confirmText: '下载',
    cancelText: '取消',
  });
  if (!ok) return;

  try {
    const res = await apiFetch('/videos/batch-download', {
      method: 'POST',
      body: { video_ids: ids },
    });
    const urls = Array.isArray(res?.download_urls) ? res.download_urls : [];
    urls.forEach((url) => triggerDownloadByUrl(url));
    if (Array.isArray(res?.missing_ids) && res.missing_ids.length) {
      spawnToast(`已下载 ${res.total_videos} 个视频，${res.missing_ids.length} 个视频已失效`, 'warning');
    } else {
      spawnToast(`已开始下载 ${res?.total_videos ?? ids.length} 个视频`, 'success');
    }
  } catch (err) {
    spawnToast(parseError(err), 'error');
  }
}

async function deleteSelectedVideos() {
  if (!state.sync.active || !state.sync.selected.size) return;
  const ids = Array.from(state.sync.selected);
  const ok = await openConfirmDialog({
    title: '批量删除',
    message: `确认删除选中的 ${ids.length} 个视频吗？`,
    confirmText: '删除',
    cancelText: '取消',
  });
  if (!ok) return;
  try {
    await Promise.all(ids.map((id) => apiFetch(`/videos/web/${id}`, { method: 'DELETE' })));
    spawnToast('所选视频已删除', 'success');
  } catch (err) {
    spawnToast(parseError(err), 'error');
  } finally {
    state.sync.selected.clear();
    state.sync.active = false;
    updateVideoSelectionUI();
    loadVideos();
  }
}

function initRoleFilter() {
  if (!dom.userRoleFilter) return;

  const options = [{ value: '', label: '全部角色' }];
  const roleOptions = [
    { value: 'user', label: '用户' },
    { value: 'business', label: '业务员' },
    { value: 'admin', label: '管理员' },
    { value: 'super_admin', label: '超级管理员' },
    { value: 'system_admin', label: '系统管理员' },
  ];

  roleOptions.forEach((opt) => options.push(opt));

  // Preserve current selection if valid
  const currentVal = dom.userRoleFilter.value;

  dom.userRoleFilter.innerHTML = '';
  options.forEach(opt => {
    const el = document.createElement('option');
    el.value = opt.value;
    el.textContent = opt.label;
    dom.userRoleFilter.appendChild(el);
  });

  if (options.some(o => o.value === currentVal)) {
    dom.userRoleFilter.value = currentVal;
  } else {
    dom.userRoleFilter.value = '';
  }
}

async function loadRoleIndex(options = {}) {
  if (!state.auth || !roleAtLeast(state.auth.role, 'admin')) return;
  hideAlert(dom.userSearchError);

  initRoleFilter();

  try {
    const keepSelectedId = options.keepSelectedId ?? state.management.selectedUserId;
    const data = await apiFetch('/users?limit=200&scope=manage');
    state.management.usersIndex = data.items || [];
    const exists = keepSelectedId && state.management.usersIndex.some((u) => u.id === keepSelectedId);
    state.management.selectedUserId = exists ? keepSelectedId : null;
    renderRoleIndex(state.management.usersIndex);
  } catch (err) {
    showAlert(dom.userSearchError, parseError(err));
  }
}

function isUserManageable(user) {
  if (!user) return false;
  if (typeof user.can_manage === 'boolean') return user.can_manage;
  const currentRole = state.auth?.role || 'user';
  const currentLevel = ROLE_PRIORITY[currentRole] ?? -1;
  const userLevel = ROLE_PRIORITY[user.role] ?? -1;
  return user.id !== state.auth?.userId && userLevel >= 0 && userLevel < currentLevel;
}

function renderRoleIndex(users) {
  if (!dom.userIndex) return;
  const visibleUsers = (users || [])
    .map((u) => ({ ...u, status: u.status !== false, can_manage: isUserManageable(u) }))
    .sort((a, b) => {
      const sa = a.status !== false ? 0 : 1;
      const sb = b.status !== false ? 0 : 1;
      if (sa !== sb) return sa - sb;
      return (ROLE_PRIORITY[b.role] ?? 0) - (ROLE_PRIORITY[a.role] ?? 0);
    });

  if (!visibleUsers.length) {
    const hasSearch = !!(dom.userSearchInput?.value?.trim() || dom.userRoleFilter?.value);
    dom.userIndex.innerHTML = `<div class="empty">${hasSearch ? '查询不到该用户' : '暂无可查看用户'}</div>`;
    state.management.selectedUserId = null;
    return;
  }

  const selectedId = state.management.selectedUserId;
  if (selectedId) {
    const selected = visibleUsers.find((u) => u.id === selectedId);
    if (selected) {
      renderUserDetailView(selected);
      return;
    }
    state.management.selectedUserId = null;
  }

  renderUserListView(visibleUsers);
}

function renderUserListView(users) {
  if (!dom.userIndex) return;
  const rows = users.map((user) => {
    const displayName = user.username || '未设置昵称';
    const displayPhone = user.telephone || '—';
    const statusText = user.status !== false ? '启用' : '禁用';
    const statusClass = user.status !== false ? 'status-enabled' : 'status-disabled';
    const count = Number.isFinite(user.video_count) ? user.video_count : 0;
    const canManage = isUserManageable(user);
    const accessClass = canManage ? 'access-manage' : 'access-readonly';
    const accessText = canManage ? '可管理' : '只读';
    return `
      <tr class="user-list-row ${canManage ? '' : 'is-readonly'}" data-action="open-user-detail" data-user-id="${user.id}" tabindex="0">
        <td>
          <div class="management-info-col">
            <img class="management-avatar" src="${escapeHtml(user.avatar_url || DEFAULT_AVATAR)}" alt="${escapeHtml(displayName)}" />
            <div>
              <div class="management-text">${escapeHtml(displayName)}</div>
              <div class="management-subtext">${escapeHtml(displayPhone)}</div>
            </div>
          </div>
        </td>
        <td>${escapeHtml(getRoleLabel(user.role))}</td>
        <td>${count}</td>
        <td><span class="user-status-badge ${statusClass}">${statusText}</span></td>
        <td><span class="user-access-badge ${accessClass}">${accessText}</span></td>
      </tr>
    `;
  }).join('');

  dom.userIndex.innerHTML = `
    <div class="management-group">
      <div class="management-header">
        <span>用户列表</span>
        <span class="management-subtext">点击任意用户进入详情</span>
      </div>
      <table class="management-table user-list-table">
        <thead>
          <tr>
            <th>用户</th>
            <th>角色</th>
            <th>视频数量</th>
            <th>状态</th>
            <th>权限</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderUserDetailView(user) {
  if (!dom.userIndex) return;
  const isEnabled = user.status !== false;
  const isPermanentRole = roleAtLeast(user.role, 'admin');
  const statusText = isEnabled ? '启用' : '禁用';
  const statusClass = isEnabled ? 'status-enabled' : 'status-disabled';
  const validUntil = isPermanentRole ? '永久' : formatDisabledUntil(user.disabled_until);
  const videoCount = Number.isFinite(user.video_count) ? user.video_count : 0;
  const canManage = isUserManageable(user);
  const readonlyNotice = !canManage
    ? '<div class="user-detail-readonly">该用户仅可查看，当前账号无权操作。</div>'
    : '';
  const actionsHtml = canManage
    ? `
      <div class="user-detail-actions">
        <button type="button" class="btn ${isEnabled ? 'btn-danger' : 'btn-primary'}" data-action="user-toggle-status" data-user-id="${user.id}">${isEnabled ? '禁用用户' : '启用用户'}</button>
        ${!isPermanentRole ? `<button type="button" class="btn btn-secondary" data-action="user-extend-validity" data-user-id="${user.id}">延期</button>` : ''}
        <button type="button" class="btn btn-secondary" data-action="user-change-role" data-user-id="${user.id}">修改角色</button>
        <button type="button" class="btn btn-secondary" data-action="user-reset-device" data-user-id="${user.id}">重置设备</button>
        <button type="button" class="btn btn-secondary" data-action="user-reset-telephone" data-user-id="${user.id}">重置手机号</button>
        <button type="button" class="btn btn-secondary" data-action="user-reset-password" data-user-id="${user.id}">重置密码</button>
        <button type="button" class="btn btn-secondary" data-action="user-set-rt-ttl" data-user-id="${user.id}">设置RT有效天数</button>
      </div>
    `
    : readonlyNotice;

  dom.userIndex.innerHTML = `
    <div class="management-group user-detail-page">
      <div class="management-header">
        <button type="button" class="btn btn-ghost" data-action="user-back-list">返回列表</button>
        <span>用户详情</span>
      </div>

      <div class="user-detail-summary">
        <img class="user-detail-avatar" src="${escapeHtml(user.avatar_url || DEFAULT_AVATAR)}" alt="${escapeHtml(user.username || '用户')}" />
        <div>
          <div class="user-detail-name">${escapeHtml(user.username || '未设置昵称')}</div>
          <div class="user-detail-phone">${escapeHtml(user.telephone || '—')}</div>
          <div class="user-detail-status"><span class="user-status-badge ${statusClass}">${statusText}</span></div>
        </div>
      </div>

      <div class="user-detail-grid">
        <div><span>角色</span><strong>${escapeHtml(getRoleLabel(user.role))}</strong></div>
        <div><span>视频数量</span><strong>${videoCount}</strong></div>
        <div><span>登录设备</span><strong>${escapeHtml(formatDeviceNameForDisplay(user.device_name))}</strong></div>
        <div><span>有效时间</span><strong>${escapeHtml(validUntil || '—')}</strong></div>
        <div><span>RT有效天数</span><strong>${Number(user.refresh_token_ttl_days || 7)}</strong></div>
      </div>

      ${actionsHtml}
    </div>
  `;
}

async function handleUserSearch(event) {
  if (event) event.preventDefault();
  hideAlert(dom.userSearchError);
  hideUserSearchSuggestions();
  const keyword = dom.userSearchInput?.value?.trim();
  const role = dom.userRoleFilter?.value || '';
  const params = new URLSearchParams();
  if (keyword) params.set('q', keyword);
  if (role) params.set('role', role);
  params.set('scope', 'manage');
  params.set('limit', '120');

  try {
    const data = await apiFetch(`/users?${params.toString()}`);
    const items = Array.isArray(data?.items) ? data.items : [];
    state.management.selectedUserId = null;
    state.management.usersIndex = items;
    renderRoleIndex(state.management.usersIndex);
  } catch (err) {
    showAlert(dom.userSearchError, parseError(err));
  }
}

function handleUserSearchInputChanged() {
  if (!dom.userSearchInput || !roleAtLeast(state.auth?.role, 'admin')) return;
  const keyword = dom.userSearchInput.value.trim();
  if (userSearchSuggestTimer) clearTimeout(userSearchSuggestTimer);

  if (!keyword) {
    state.management.userSearchSuggestions = [];
    hideUserSearchSuggestions();
    return;
  }

  userSearchSuggestTimer = setTimeout(() => fetchUserSearchSuggestions(keyword), 220);
}

async function fetchUserSearchSuggestions(keyword) {
  try {
    const params = new URLSearchParams();
    params.set('q', keyword);
    params.set('scope', 'manage');
    params.set('limit', '8');

    const role = dom.userRoleFilter?.value || '';
    if (role) params.set('role', role);

    const data = await apiFetch(`/users?${params.toString()}`);
    const items = Array.isArray(data?.items) ? data.items : [];
    state.management.userSearchSuggestions = items;
    renderUserSearchSuggestions();
  } catch (err) {
    console.warn('[platform] fetch user search suggestions failed', err);
    state.management.userSearchSuggestions = [];
    hideUserSearchSuggestions();
  }
}

function renderUserSearchSuggestions() {
  if (!dom.userSearchSuggestions) return;
  const items = state.management.userSearchSuggestions || [];
  if (!items.length) {
    hideUserSearchSuggestions();
    return;
  }

  dom.userSearchSuggestions.innerHTML = items
    .map((item) => {
      const name = item.username || maskTelephone(item.telephone) || item.id.slice(0, 8);
      const meta = [item.telephone ? maskTelephone(item.telephone) : '', getRoleLabel(item.role)].filter(Boolean).join(' · ');
      return `<button type="button" data-id="${item.id}" data-keyword="${escapeHtml(name)}">${escapeHtml(name)}${meta ? ` <span>${escapeHtml(meta)}</span>` : ''}</button>`;
    })
    .join('');
  dom.userSearchSuggestions.hidden = false;
}

function hideUserSearchSuggestions() {
  if (!dom.userSearchSuggestions) return;
  dom.userSearchSuggestions.hidden = true;
  dom.userSearchSuggestions.innerHTML = '';
}

function handleUserSearchSuggestionClick(e) {
  const btn = e.target.closest('button');
  if (!btn) return;

  const id = btn.dataset.id;
  const selected = (state.management.userSearchSuggestions || []).find((item) => item.id === id);
  if (!selected) return;

  if (dom.userSearchInput) {
    dom.userSearchInput.value = selected.username || selected.telephone || '';
  }
  state.management.selectedUserId = selected.id;
  state.management.usersIndex = [selected];
  hideUserSearchSuggestions();
  renderRoleIndex(state.management.usersIndex);
}

async function promptRoleSelection(availableRoles, currentRole) {
  if (!availableRoles.length) return null;
  const raw = await openSelectDialog({
    title: '选择目标角色',
    message: `当前角色：${getRoleLabel(currentRole)}`,
    label: '目标角色',
    options: availableRoles.map((role) => ({
      value: role,
      label: getRoleLabel(role),
      description: role,
    })),
    defaultValue: availableRoles[0],
    confirmText: '下一步',
    cancelText: '取消',
    required: true,
    requiredMessage: '请选择目标角色',
  });
  return raw || null;
}

function getRoleOptionsForActor(actorRole, targetRole, targetId) {
  const allowed = [];

  // Define allowed roles to assign based on actor role
  // Can only assign roles STRICTLY BELOW current level.
  // Cannot assign same level role.
  if (actorRole === 'system_admin') {
     allowed.push('user', 'business', 'admin', 'super_admin');
  } else if (actorRole === 'super_admin') {
    allowed.push('user', 'business', 'admin');
  } else if (actorRole === 'admin') {
    allowed.push('user', 'business');
  } else if (actorRole === 'business') {
    allowed.push('user');
  }

  // If the target user currently has a role that is not in the allowed list (e.g. higher role),
  // we generally shouldn't be editing them. But if we are here, we might be demoting.

  return allowed;
}

function handleUserResultAction(event) {
  void event;
}

function findManagedUserById(userId) {
  const users = state.management.usersIndex || [];
  return users.find((u) => u.id === userId) || null;
}

async function handleUserIndexClick(event) {
  const target = event.target;
  const actionEl = target.closest('[data-action]');
  if (!actionEl) return;

  const action = actionEl.dataset.action;
  const userId = actionEl.dataset.userId || actionEl.closest('[data-user-id]')?.dataset.userId;

  if (action === 'open-user-detail' && userId) {
    state.management.selectedUserId = userId;
    renderRoleIndex(state.management.usersIndex);
    return;
  }

  if (action === 'user-back-list') {
    state.management.selectedUserId = null;
    renderRoleIndex(state.management.usersIndex);
    return;
  }

  if (!userId) return;
  const user = findManagedUserById(userId);
  if (!user) {
    spawnToast('用户信息不存在，请刷新后重试', 'error');
    return;
  }
  if (!isUserManageable(user)) {
    spawnToast('该用户仅可查看，当前账号无权操作', 'warning');
    return;
  }

  try {
    if (action === 'user-toggle-status') {
      const isEnabled = user.status !== false;
      const ok = await openConfirmDialog({
        title: isEnabled ? '确认禁用用户？' : '确认启用用户？',
        message: isEnabled ? '禁用后用户将无法登录。' : '启用后用户可恢复登录。',
        confirmText: isEnabled ? '禁用' : '启用',
        cancelText: '取消',
      });
      if (!ok) return;
      let durationDays = null;
      if (!isEnabled && !roleAtLeast(user.role, 'admin')) {
        durationDays = await promptDurationDays(30, '请输入启用时长（天）');
        if (!durationDays) return;
      }
      await updateUserStatus(userId, !isEnabled, durationDays);
      await loadRoleIndex({ keepSelectedId: userId });
      spawnToast('用户状态已更新', 'success');
      return;
    }

    if (action === 'user-change-role') {
      const actorRole = state.auth?.role || 'user';
      const options = getRoleOptionsForActor(actorRole, user.role, userId).filter((role) => role !== user.role);
      if (!options.length) {
        spawnToast('当前账号没有可调整的目标角色', 'warning');
        return;
      }

      const nextRole = await promptRoleSelection(options, user.role);
      if (!nextRole || nextRole === user.role) return;

      const ok = await openConfirmDialog({
        title: '修改用户角色',
        message: `确认将该用户从“${getRoleLabel(user.role)}”调整为“${getRoleLabel(nextRole)}”吗？`,
        confirmText: '确认修改',
        cancelText: '取消',
      });
      if (!ok) return;

      await apiFetch(`/users/${userId}/role`, {
        method: 'PATCH',
        body: { role: nextRole },
      });
      await loadRoleIndex({ keepSelectedId: userId });
      spawnToast('用户角色已更新', 'success');
      return;
    }

    if (action === 'user-reset-device') {
      const ok = await openConfirmDialog({
        title: '重置设备',
        message: '确认重置该用户设备标识并吊销 App 端登录吗？',
        confirmText: '确认重置',
        cancelText: '取消',
      });
      if (!ok) return;
      await apiFetch(`/users/${userId}/device/reset`, {
        method: 'PATCH',
        body: { clear_name: true },
      });
      await loadRoleIndex({ keepSelectedId: userId });
      spawnToast('设备已重置', 'success');
      return;
    }

    if (action === 'user-extend-validity') {
      const days = await promptDurationDays(30, '请输入延期天数');
      if (!days) return;
      await updateUserStatus(userId, true, days);
      await loadRoleIndex({ keepSelectedId: userId });
      spawnToast('有效时间已延期', 'success');
      return;
    }

    if (action === 'user-reset-telephone') {
      const trimmed = await openInputDialog({
        title: '重置手机号',
        message: '请输入新的手机号（11位）',
        label: '手机号',
        placeholder: '例如 13800138000',
        defaultValue: user.telephone || '',
        inputType: 'tel',
        confirmText: '确认重置',
        cancelText: '取消',
        required: true,
        requiredMessage: '手机号格式不正确，请输入11位数字',
        validate: (value) => (/^\d{11}$/.test(value) ? true : '手机号格式不正确，请输入11位数字'),
      });
      if (trimmed === null) return;
      await apiFetch(`/users/${userId}/telephone/reset`, {
        method: 'PATCH',
        body: { new_telephone: trimmed },
      });
      await loadRoleIndex({ keepSelectedId: userId });
      spawnToast('手机号已重置', 'success');
      return;
    }

    if (action === 'user-reset-password') {
      const nextPwd = await openInputDialog({
        title: '重置密码',
        message: '请输入新密码（8-16位，字母+数字）',
        label: '新密码',
        placeholder: '8-16位字母+数字',
        defaultValue: '',
        inputType: 'password',
        confirmText: '确认重置',
        cancelText: '取消',
        required: true,
        requiredMessage: '密码需8-16位且包含字母和数字',
        validate: (value) => (isPasswordValid(value) ? true : '密码需8-16位且包含字母和数字'),
      });
      if (nextPwd === null) return;
      await apiFetch(`/users/${userId}/password/reset`, {
        method: 'PATCH',
        body: { new_password: nextPwd },
      });
      spawnToast('密码已重置', 'success');
      return;
    }

    if (action === 'user-set-rt-ttl') {
      const currentDays = Number(user.refresh_token_ttl_days || 7);
      const raw = await openInputDialog({
        title: '设置 RT 有效天数',
        message: '请输入 RT 有效期天数（1-365）',
        label: 'RT 天数',
        placeholder: '1-365',
        defaultValue: String(currentDays),
        inputType: 'number',
        confirmText: '确认设置',
        cancelText: '取消',
        required: true,
        requiredMessage: '请输入1到365之间的整数',
        validate: (value) => {
          const days = Number(value);
          return Number.isInteger(days) && days >= 1 && days <= 365
            ? true
            : '请输入1到365之间的整数';
        },
      });
      if (raw === null) return;
      const days = Number(String(raw).trim());
      await apiFetch(`/users/${userId}/rt-ttl`, {
        method: 'PATCH',
        body: { rt_ttl_days: days },
      });
      await loadRoleIndex({ keepSelectedId: userId });
      spawnToast('RT有效期已更新', 'success');
      return;
    }
  } catch (err) {
    spawnToast(parseError(err), 'error');
  }
}

function handleUserIndexKeydown(event) {
  const row = event.target.closest('[data-action="open-user-detail"]');
  if (!row) return;
  if (event.key !== 'Enter' && event.key !== ' ') return;
  event.preventDefault();
  state.management.selectedUserId = row.dataset.userId;
  renderRoleIndex(state.management.usersIndex);
}

async function updateUserStatus(userId, enabled, durationDays = null) {
  hideAlert(dom.userSearchError);
  const body = { enabled };
  if (durationDays) body.duration_days = durationDays;
  const result = await apiFetch(`/users/${userId}/status`, {
    method: 'PATCH',
    body,
  });

  const syncStatus = (collection) => {
    if (!Array.isArray(collection)) return;
    const user = collection.find((item) => item.id === userId);
    if (user) {
      user.status = result.status;
      user.role = result.role;
      user.disabled_until = result.disabled_until;
    }
  };

  syncStatus(state.management.users);
  syncStatus(state.management.usersIndex);

  return result;
}

function canDeleteVideo(video) {
  if (isDeletedView()) return false;
  if (!state.auth) return false;
  if (roleAtLeast(state.auth.role, 'admin')) return true;
  const currentId = state.auth.userId;
  if (!currentId) return false;
  const ownerIds = new Set();
  if (video.owner_id) ownerIds.add(String(video.owner_id));
  if (Array.isArray(video.owners)) {
    video.owners.forEach((owner) => {
      if (owner?.user_id) ownerIds.add(String(owner.user_id));
    });
  }
  return ownerIds.has(currentId);
}

function isDeletedView() {
  return String(state.filters.view || '').trim() === 'deleted';
}

function maskTelephone(value) {
  if (!value) return '—';
  if (value.length >= 7) {
    return value.replace(/(\d{3})\d{4}(\d{2,})/, '$1****$2');
  }
  return value;
}

function maskId(value) {
  if (!value) return '—';
  const raw = String(value);
  if (raw.length <= 6) return raw;
  return `${raw.slice(0, 3)}***${raw.slice(-3)}`;
}

function formatDateTime(value) {
  if (!value) return '';
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', { hour12: false });
}

function formatDisabledUntil(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('zh-CN');
}

function formatDeviceNameForDisplay(value) {
  if (!value) return '—';
  const raw = String(value).trim();
  if (!raw) return '—';
  const compact = raw.replace(/\s*\([A-Za-z]+\d+[\s,]\d+\)\s*$/, '').trim();
  return compact || raw;
}

function resolveCreatorLabel(userId) {
  if (!userId && state.profile?.data?.id) {
    userId = state.profile.data.id;
  }
  if (!userId) {
    return maskTelephone(state.auth?.telephone) || '—';
  }
  const cached = state.userCache?.get(userId);
  if (cached) {
    return cached.telephone ? maskTelephone(cached.telephone) : (cached.username || '—');
  }
  if (state.profile?.data && state.profile.data.id === userId) {
    const info = state.profile.data;
    const label = info.telephone ? maskTelephone(info.telephone) : (info.username || '—');
    state.userCache.set(userId, { username: info.username, telephone: info.telephone });
    return label;
  }
  if (state.auth?.userId === userId) {
    const tel = state.profile?.data?.telephone || state.auth?.telephone;
    const label = tel ? maskTelephone(tel) : (state.profile?.data?.username || '—');
    state.userCache.set(userId, { username: state.profile?.data?.username || null, telephone: state.profile?.data?.telephone || state.auth?.telephone || null });
    return label;
  }
  return '—';
}

function resolveUserLabel(userId) {
  if (!userId) return '—';
  const cached = state.userCache?.get(userId);
  if (cached) {
    if (cached.telephone) return maskTelephone(cached.telephone);
  }
  return fetchUserLabelById(userId);
}

function fetchUserLabelById(userId) {
  const userIndex = state.management.usersIndex || [];
  const found = userIndex.find((u) => u.id === userId);
  if (found) {
    ensureUserCached(userId, found);
    if (found.telephone) return maskTelephone(found.telephone);
  }
  if (state.profile?.data && state.profile.data.id === userId) {
    ensureUserCached(userId, state.profile.data);
    return maskTelephone(state.profile.data.telephone) || '—';
  }
  if (state.auth?.userId === userId) {
    const tel = state.profile?.data?.telephone || state.auth.telephone;
    ensureUserCached(userId, { username: state.profile?.data?.username || null, telephone: tel || null });
    return tel ? maskTelephone(tel) : '—';
  }
  // 无法查到用户信息时，不显示 ID，返回空占位
  return '—';
}

function ensureUserCached(userId, source) {
  if (!state.userCache) state.userCache = new Map();
  state.userCache.set(userId, {
    username: source.username || null,
    telephone: source.telephone || null,
  });
}

function escapeHtml(str) {
  if (typeof str !== 'string') return '';
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return str.replace(/[&<>"']/g, (ch) => map[ch] || ch);
}

function loadAuth() {
  try {
    // 1. 优先检查 URL 参数中的 login_token (跨域登录传递)
    const params = new URLSearchParams(window.location.search);
    const loginToken = params.get('login_token');

    if (loginToken) {
      try {
        // base64 url safe decode
        const b64 = loginToken.replace(/-/g, '+').replace(/_/g, '/');
        // decodeURIComponent(escape(window.atob(b64))) to handle utf8 if any
        // but our payload is mostly ascii except maybe unused fields. JSON.parse handles unicode in string if escaped properly?
        // standard atob should be enough for JSON string unless it has unicode chars.
        // Let's use robust decoding
        const jsonStr = decodeURIComponent(Array.from(atob(b64)).map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join(''));
        const authPayload = JSON.parse(jsonStr);

        if (authPayload && authPayload.accessToken) {
            console.log("Successfully logged in via URL token");
            // Save to localStorage
            localStorage.setItem('platformAuth', JSON.stringify(authPayload));

            // Clean URL
            params.delete('login_token');
            const newSearch = params.toString();
            const newUrl = window.location.pathname + (newSearch ? '?' + newSearch : '') + window.location.hash;
            window.history.replaceState({}, '', newUrl);

            return authPayload;
        }
      } catch (e) {
        console.error("Failed to parse login_token", e);
      }
    }

    // 2. Fallback to localStorage
    const raw = localStorage.getItem('platformAuth');
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed.accessToken) return null;
    return parsed;
  } catch (err) {
    console.warn('loadAuth error', err);
    return null;
  }
}

function saveAuth(payload) {
  if (!payload) {
    localStorage.removeItem('platformAuth');
    state.auth = null;
    updateAdminFiltersVisibility();
    return;
  }
  state.auth = payload;
  localStorage.setItem('platformAuth', JSON.stringify(payload));
  updateAdminFiltersVisibility();
}

function decodeJwt(token) {
  if (!token) return null;
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const decoded = decodeURIComponent(atob(base64).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join(''));
    return JSON.parse(decoded);
  } catch (err) {
    console.warn('decode error', err);
    return null;
  }
}

function syncAuthState() {
  if (!state.auth) {
    redirectToLogin();
    return;
  }
  if (!ensureAllowedRole()) return;
  updateNavUserDisplay();
  document.body.classList.add('logged-in');
  const isAdmin = roleAtLeast(state.auth.role, 'admin');
  if (dom.videoToolbar) dom.videoToolbar.hidden = !isAdmin;
  if (!isAdmin) {
    state.sync.active = false;
    state.sync.selected.clear();
    updateVideoSelectionUI();
  }
  configureManagementVisibility();
  updateMainPaneVisibility();
}


function setSession(res, telephone) {
  const payload = decodeJwt(res.access_token);
  const userId = res.user_id || payload?.sub;
  const role = payload?.role || 'user';
  const expiresAt = payload?.exp ? payload.exp * 1000 : null;
  saveAuth({
    accessToken: res.access_token,
    refreshToken: res.refresh_token,
    userId,
    role,
    telephone,
    expiresAt,
  });
}

async function apiFetch(path, { method = 'GET', body, headers = {}, skipAuth = false, _retry = false } = {}) {
  if (!state.apiBase) throw new Error('API 地址未设置');
  const opts = { method, headers: { ...headers } };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  if (!skipAuth && state.auth?.accessToken) {
    opts.headers['Authorization'] = `Bearer ${state.auth.accessToken}`;
  }
  const res = await fetch(`${state.apiBase}${path}`, opts);
  if (res.status === 401 && !skipAuth && state.auth?.refreshToken && !_retry) {
    const refreshed = await refreshToken();
    if (refreshed) {
      return apiFetch(path, { method, body, headers, skipAuth, _retry: true });
    }
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `请求失败：${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

async function refreshToken() {
  try {
    const data = await apiFetch('/auth/refresh', {
      method: 'POST',
      body: { refresh_token: state.auth.refreshToken },
      skipAuth: true,
    });
    setSession({
      access_token: data.access_token,
      refresh_token: data.refresh_token || state.auth.refreshToken,
      user_id: state.auth.userId,
    }, state.auth.telephone);
    syncAuthState();
    return true;
  } catch (err) {
    console.warn('refresh error', err);
    logout();
    return false;
  }
}

function logout() {
  if (state.auth && state.auth.refreshToken) {
    fetch(`${state.apiBase}/auth/logout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: state.auth.refreshToken })
    }).catch(console.error);
  }
  saveAuth(null);
  redirectToLogin();
}

function initCategoryBar() {
  if (!dom.categoryBar) return;
  dom.categoryBar.addEventListener('click', (e) => {
    const target = e.target.closest('.category');
    if (!target) return;
    dom.categoryBar.querySelectorAll('.category').forEach((el) => el.classList.remove('active'));
    target.classList.add('active');
    state.filters.view = target.dataset.view ?? '';
    state.pagination.page = 1;
    if (isDeletedView()) {
      state.sync.active = false;
      state.sync.selected.clear();
      updateVideoSelectionUI();
    }
    loadVideos();
  });
}

function initSearch() {
  if (!dom.searchBtn) return;
  dom.searchBtn.addEventListener('click', () => {
    state.filters.search = dom.searchInput.value.trim();
    loadVideos();
  });
  dom.searchInput?.addEventListener('keyup', (e) => {
    if (e.key !== 'Enter') return;
    state.filters.search = dom.searchInput.value.trim();
    loadVideos();
  });
}

async function loadVideos() {
  if (!state.auth) return;
  dom.gallerySection?.classList.add('gallery-switching');
  dom.grid?.classList.add('gallery-switching');
  const isManager = roleAtLeast(state.auth.role, 'admin');
  console.debug('[platform] loadVideos start', {
    apiBase: state.apiBase,
    isManager,
    filters: { ...state.filters },
    authRole: state.auth.role,
  });

  // Use state.pagination
  const params = new URLSearchParams({
    sort_by: 'created_at',
    sort_order: 'desc',
    page: String(state.pagination.page),
    page_size: String(state.pagination.limit),
  });

  const viewFilter = String(state.filters.view || '').trim();
  if (viewFilter === 'deleted') {
    params.set('deleted_only', 'true');
    params.set('status', '');
  } else if (viewFilter === 'favorite') {
    params.set('is_favorited', 'true');
  } else if (/^\d+$/.test(viewFilter)) {
    params.set('view_type', viewFilter);
  }

  if (isManager) {
    if (state.filters.ownerId) {
      params.set('owner_id', state.filters.ownerId);
    }
    if (state.filters.wechatKeyword) {
      params.set('wechat_keyword', state.filters.wechatKeyword);
    }
  }

  if (state.filters.pairedStatus === 'paired') {
    params.set('paired_only', 'true');
  }

  if (state.filters.dateStart) {
    params.set('created_from', `${state.filters.dateStart}T00:00:00`);
  }
  if (state.filters.dateEnd) {
    params.set('created_to', `${state.filters.dateEnd}T23:59:59`);
  }
  try {
    const endpoint = isManager ? '/videos/admin' : `/videos/user/${state.auth.userId}`;
    const res = await apiFetch(`${endpoint}?${params.toString()}`);
    let items = res.items || [];

    const wechatProfiles = res.wechat_profiles || {};
    const wechatUserProfiles = res.wechat_user_profiles || {};
    items.forEach(item => {
      const unionid = item.wechat_unionid;
      const profile = unionid ? wechatUserProfiles[unionid] : null;
      const fallbackName = unionid && wechatProfiles[unionid] ? wechatProfiles[unionid] : null;
      item.wechat_user_name = profile?.name || fallbackName || '游客';
      item.wechat_user_avatar = profile?.avatar_url || '';
    });

    const rootCandidate = items.find((item) => typeof item.file_path === 'string');
    if (rootCandidate?.file_path) {
      const matched = rootCandidate.file_path.match(/^(.*\/video)\//);
      if (matched) {
        localStorage.setItem('videoRootCache', matched[1]);
      }
    }

    if (state.filters.search) {
      const keyword = state.filters.search.toLowerCase();
      items = items.filter((item) => {
        const owners = Array.isArray(item.owners) ? item.owners : [];
        const ownerMatch = owners.some((owner) =>
          (owner.username && owner.username.toLowerCase().includes(keyword)) ||
          (owner.telephone && owner.telephone.includes(keyword))
        );
        return (
          (item.title && item.title.toLowerCase().includes(keyword)) ||
          ownerMatch
        );
      });
    }

    state.videos = items;
    state.pagination.total = res.total ?? items.length;
    state.videosTotal = state.pagination.total;

    renderVideos();
    console.debug('[platform] loadVideos success', { count: state.videos.length });
  } catch (err) {
    if (/401/.test(err.message)) {
      logout();
    } else {
      console.error('[platform] loadVideos failed', err);
      spawnToast('加载视频失败：' + err.message, 'error');
    }
    dom.gallerySection?.classList.remove('gallery-switching');
    dom.grid?.classList.remove('gallery-switching');
  }
}

function renderVideos() {
  dom.grid.innerHTML = '';
  const deletedView = isDeletedView();
  if (!state.videos.length) {
    dom.empty.hidden = false;
    if (deletedView) {
      dom.empty.textContent = '已删除页暂无视频。';
    } else if (state.filters.ownerId || state.filters.ownerKeyword || state.filters.wechatKeyword || state.filters.pairedStatus) {
      dom.empty.textContent = '未找到匹配的视频。';
    } else if (roleAtLeast(state.auth?.role, 'admin')) {
      dom.empty.textContent = '目前没有可展示的视频，可以调整筛选条件试试。';
    } else {
      dom.empty.textContent = '暂无视频，快去上传一个吧。';
    }
  } else {
    dom.empty.hidden = true;
    dom.empty.textContent = '暂无视频，快去上传一个吧。';
    const fragment = document.createDocumentFragment();
    state.videos.forEach((video) => {
      fragment.appendChild(createCard(video));
    });
    dom.grid.appendChild(fragment);
  }

  if (state.sync.active && dom.videoSelectionInfo) {
    dom.videoSelectionInfo.textContent = `已选择 ${state.sync.selected.size} 个视频`;
  }

  updatePaginationUI();

  requestAnimationFrame(() => {
    dom.gallerySection?.classList.remove('gallery-switching');
    dom.grid?.classList.remove('gallery-switching');
    dom.gallerySection?.classList.add('gallery-ready');
    dom.grid?.classList.add('gallery-ready');
  });
}

function updatePaginationUI() {
  if (!dom.videoPagination) return;

  const { page, limit, total } = state.pagination;
  const totalPages = Math.ceil(total / limit) || 1;
  const hasVideos = total > 0;

  dom.videoPagination.hidden = !hasVideos;
  if (!hasVideos) return;

  if (dom.videoTotalCount) dom.videoTotalCount.textContent = total;
  // Update to more explicit format
  if (dom.videoCurrentPage) dom.videoCurrentPage.textContent = `第 ${page} 页 / 共 ${totalPages} 页`;

  if (dom.videoPrevPage) {
      dom.videoPrevPage.disabled = page <= 1;
      dom.videoPrevPage.onclick = () => changePage(page - 1);
  }

  if (dom.videoNextPage) {
      dom.videoNextPage.disabled = page >= totalPages;
      dom.videoNextPage.onclick = () => changePage(page + 1);
  }

  let jumpContainer = dom.videoPagination.querySelector('.pagination-jump');
  if (!jumpContainer) {
      jumpContainer = document.createElement('div');
      jumpContainer.className = 'pagination-jump';

      const buttonsContainer = dom.videoPagination.querySelector('.pagination-buttons');
      if (buttonsContainer) buttonsContainer.appendChild(jumpContainer);
  }

  jumpContainer.innerHTML = `
    <span>跳转至</span>
    <input type="number" min="1" max="${totalPages}" value="${page}" aria-label="页码">
    <span>页</span>
  `;

  const jumpInput = jumpContainer.querySelector('input');
  const go = () => {
    let val = parseInt(jumpInput.value);
    if (!isNaN(val) && val >= 1 && val <= totalPages) {
        if (val !== page) changePage(val);
    } else {
        // Reset to current page if invalid
        jumpInput.value = page;
    }
  };

  jumpInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
          go();
          jumpInput.blur();
      }
  });
}

async function changePage(newPage) {
    if (newPage < 1) return;
    state.pagination.page = newPage;

    // Custom logic to scroll to top of content below header
    if (dom.gallerySection) {
        // Sticky header is roughly 80-90px. Add buffer.
        // We want to scroll so gallery top is visible.
        // But the user said "below 'Select'". 'Select' is in video-toolbar.
        // So we might want to align to the toolbar.
        // Let's scroll so content starts at top - offset.

        const offset = 100; // Header + some padding
        const element = dom.gallerySection;
        const elementPosition = element.getBoundingClientRect().top;
        const offsetPosition = elementPosition + window.pageYOffset - offset;

        window.scrollTo({
            top: offsetPosition,
            behavior: "auto" // Instant scroll for faster feel
        });
    }

    await loadVideos();
}

function getVideoPlaybackUrl(video) {
  return video?.file_url || resolveMediaUrl(video?.file_path);
}

function startCardPreview(card, video) {
  if (!card || state.sync.active || card._previewVideo) return;
  const url = getVideoPlaybackUrl(video);
  if (!url) return;
  const cover = card.querySelector('.card-cover');
  if (!cover) return;

  const preview = document.createElement('video');
  preview.className = 'card-preview-video';
  preview.src = url;
  preview.muted = true;
  preview.loop = true;
  preview.playsInline = true;
  preview.preload = 'auto';
  preview.controls = false;
  card._previewVideo = preview;

  preview.addEventListener('loadeddata', () => {
    if (card._previewVideo === preview) {
      card.classList.add('is-previewing');
    }
  });

  cover.appendChild(preview);
  preview.play().catch(() => stopCardPreview(card));
}

function stopCardPreview(card) {
  const preview = card?._previewVideo;
  if (!preview) return;
  preview.pause();
  preview.removeAttribute('src');
  preview.load();
  preview.remove();
  card._previewVideo = null;
  card.classList.remove('is-previewing');
}

function createCard(video) {
  const card = document.createElement('article');
  card.className = 'card';
  card.dataset.id = video.id;
  const cover = document.createElement('div');
  cover.className = 'card-cover';
  cover.style.position = 'relative';

  // Fix thumbnail URL logic
  let thumbSrc = video.thumb_url || video.thumb_path;
  const isHttp = thumbSrc && /^https?:\/\//i.test(thumbSrc);

  // If we have a path but it's not http(s), we need to prepend the origin
  if (thumbSrc && !isHttp && thumbSrc.startsWith('/')) {
      thumbSrc = `${window.location.origin}${thumbSrc}`;
  } else if (thumbSrc && !isHttp && !thumbSrc.startsWith('/')) {
      // In case it's a relative path without leading slash, though less likely given context
      // Assuming it might be "thumbs/..."
      thumbSrc = `${window.location.origin}/${thumbSrc}`;
  }

  // Now thumbSrc should be absolute URL if it existed
  const thumb = document.createElement(thumbSrc ? 'img' : 'div');

  if (thumbSrc) {
    thumb.src = thumbSrc;
    thumb.className = 'card-thumb';
    thumb.alt = video.title || 'thumb';
    // Add error handler to fallback?
  } else {
    thumb.className = 'card-thumb placeholder';
    thumb.textContent = '暂无缩略图';
  }
  cover.appendChild(thumb);
  const play = document.createElement('div');
  play.className = 'play-icon';
  play.innerHTML = '<span>点击播放</span>';
  cover.appendChild(play);

  const isPrimaryPaired = Boolean(video.pair_session_id && video.is_primary_video);
  const isFavorite = Boolean(video.is_favorited || video.isFavorited);
  const hasDrawFile = Boolean(video.drawed_path || video.multi_drawed_path);

  const pairedBadge = document.createElement('div');
  pairedBadge.className = `card-paired-badge${isPrimaryPaired ? ' is-active' : ''}`;
  pairedBadge.title = isPrimaryPaired ? '这是关联主视频，包含多角度机位' : '非关联主视频';
  pairedBadge.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>';
  cover.appendChild(pairedBadge);

  const favBadge = document.createElement('div');
  favBadge.className = `card-favorite-badge${isFavorite ? ' is-active' : ''}`;
  favBadge.title = isFavorite ? '已收藏' : '未收藏';
  favBadge.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>';
  cover.appendChild(favBadge);

  const drawBadge = document.createElement('div');
  drawBadge.className = `card-draw-badge${hasDrawFile ? ' is-active' : ''}`;
  drawBadge.title = hasDrawFile ? '已有画线文件' : '暂无画线文件';
  drawBadge.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"></path><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"></path></svg>';
  cover.appendChild(drawBadge);

  card.appendChild(cover);

  if (state.sync.active) {
    card.classList.add('card-selectable');
    if (state.sync.selected.has(video.id)) {
      card.classList.add('selected');
    }
    const indicator = document.createElement('div');
    indicator.className = 'card-select-indicator';
    indicator.textContent = state.sync.selected.has(video.id) ? '✓' : '';
    cover.appendChild(indicator);
  } else if (canDeleteVideo(video)) {
    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className = 'card-delete';
    deleteBtn.textContent = '删除';
    deleteBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      confirmDeleteVideo(video);
    });
    cover.appendChild(deleteBtn);
  }

  card.addEventListener('click', (e) => {
    if (state.sync.active) {
      e.preventDefault();
      e.stopPropagation();
      toggleVideoSelection(video, card);
      return;
    }
    openPlayer(video);
  });
  card.addEventListener('mouseenter', () => startCardPreview(card, video));
  card.addEventListener('mouseleave', () => stopCardPreview(card));
  card.addEventListener('focusin', () => startCardPreview(card, video));
  card.addEventListener('focusout', () => stopCardPreview(card));

  const body = document.createElement('div');
  body.className = 'card-body';

  const title = document.createElement('div');
  title.className = 'card-title';
  const titleText = video.title || formatDateTime(video.created_at) || '未命名视频';
  title.textContent = titleText;
  body.appendChild(title);

  const meta = document.createElement('div');
  meta.className = 'card-meta';
  const owners = Array.isArray(video.owners) ? video.owners : [];
  const primary = owners[0] || {};

  const rawName = primary.username || video.owner_username;
  const rawPhone = primary.telephone || video.owner_telephone;
  const displayName = rawName || (rawPhone ? maskTelephone(rawPhone) : '未知账号');
  const displayPhone = (rawName && rawPhone) ? ` (${maskTelephone(rawPhone)})` : '';

  const ownerBox = document.createElement('div');
  ownerBox.className = 'card-owner';

  const lineUser = document.createElement('div');
  lineUser.className = 'card-owner-name';
  lineUser.style.fontSize = '0.85em';
  lineUser.style.color = '#666';
  lineUser.textContent = `用户：${displayName}${displayPhone}`;
  ownerBox.appendChild(lineUser);

  const wechatLabel = video.wechat_user_name || '游客';
  const lineWechat = document.createElement('div');
  lineWechat.className = 'card-owner-wechat';

  if (wechatLabel === '游客') {
    const guestTag = document.createElement('span');
    guestTag.className = 'card-guest-tag';
    guestTag.textContent = '游客';
    lineWechat.append(guestTag);
  } else {
    const wechatTag = document.createElement('span');
    wechatTag.className = 'card-wechat-tag';
    wechatTag.textContent = '微信';

    const wechatAvatar = document.createElement('img');
    wechatAvatar.className = 'card-owner-wechat-avatar';
    wechatAvatar.src = video.wechat_user_avatar || DEFAULT_AVATAR;
    wechatAvatar.alt = wechatLabel;
    wechatAvatar.onerror = () => {
      wechatAvatar.src = DEFAULT_AVATAR;
    };

    const wechatText = document.createElement('span');
    wechatText.textContent = wechatLabel;

    lineWechat.append(wechatTag, wechatAvatar, wechatText);
  }

  ownerBox.appendChild(lineWechat);

  meta.appendChild(ownerBox);

  body.appendChild(meta);

  card.appendChild(body);
  return card;
}

async function confirmDeleteVideo(video) {
  if (!video || !state.auth) return;
  const ok = await openConfirmDialog({
    title: '删除视频',
    message: '确认删除该视频吗？删除后将移入回收站。',
    confirmText: '删除',
    cancelText: '取消',
  });
  if (!ok) return;
  try {
    await apiFetch(`/videos/web/${video.id}`, { method: 'DELETE' });
    spawnToast('视频已删除', 'success');
    state.videos = state.videos.filter((item) => item.id !== video.id);
    if (state.sync.selected.has(video.id)) {
      state.sync.selected.delete(video.id);
    }
    renderVideos();
  } catch (err) {
    spawnToast(parseError(err), 'error');
  }
}

function formatBytes(bytes) {
  const num = Number(bytes);
  if (!Number.isFinite(num) || num <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = num;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx++;
  }
  return `${value.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function mapView(value) {
  switch (Number(value)) {
    case 0: return '侧面';
    case 1: return '正面';
    case 2: return '专业';
    case 3: return '顶部';
    case 4: return '其他';
    default: return '未知';
  }
}

function initUploadDrawer() {
  if (!dom.openUpload || !dom.drawer || !dom.drawerBackdrop) return;
  dom.openUpload.addEventListener('click', () => {
    if (!state.auth) {
      redirectToLogin();
      return;
    }
    dom.drawer.classList.add('open');
    dom.drawerBackdrop.classList.add('show');
  });
  dom.drawerBackdrop.addEventListener('click', closeDrawer);
  dom.uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!state.auth) {
      redirectToLogin();
      return;
    }
    const formData = new FormData(dom.uploadForm);
    dom.uploadError.hidden = true;
    dom.uploadSuccess.hidden = true;
    try {
      await apiFetch('/videos/upload', { method: 'POST', body: formData });
      dom.uploadSuccess.textContent = '上传成功，正在处理视频。';
      dom.uploadSuccess.hidden = false;
      dom.uploadForm.reset();
      closeDrawer();
      setTimeout(loadVideos, 800);
    } catch (err) {
      dom.uploadError.textContent = err.message;
      dom.uploadError.hidden = false;
    }
  });
}

function closeDrawer() {
  dom.drawer.classList.remove('open');
  dom.drawerBackdrop.classList.remove('show');
}

function initNavBar() {
  dom.navLogout?.addEventListener('click', logout);
  dom.navProfileBtn?.addEventListener('click', (e) => {
    e.preventDefault();
    openProfileSection();
  });
  dom.navAvatarBtn?.addEventListener('click', () => openProfileSection());
  initUserDropdown();
  updateNavUserDisplay();
}

function updateNavUserDisplay() {
  let label = '--';
  if (state.auth?.telephone) {
    label = maskTelephone(state.auth.telephone);
  } else if (state.auth?.userId) {
    label = maskId(state.auth.userId);
  }
  if (dom.navUserLabel) dom.navUserLabel.textContent = label || '--';
  const avatar = state.profile?.data?.avatar_url || state.auth?.avatar_url || DEFAULT_AVATAR;
  if (dom.navAvatarImg) {
    dom.navAvatarImg.src = avatar || DEFAULT_AVATAR;
    dom.navAvatarImg.onerror = () => {
      dom.navAvatarImg.src = DEFAULT_AVATAR;
    };
  }
}

function initUserDropdown() {
  if (!dom.navUserDropdown) return;
  const dropdown = dom.navUserDropdown;
  const showMenu = () => {
    clearTimeout(userMenuHideTimer);
    dropdown.classList.add('open');
  };
  const hideMenu = () => {
    clearTimeout(userMenuHideTimer);
    userMenuHideTimer = setTimeout(() => dropdown.classList.remove('open'), 350);
  };
  dropdown.addEventListener('mouseenter', showMenu);
  dropdown.addEventListener('mouseleave', hideMenu);
  dropdown.addEventListener('focusin', showMenu);
  dropdown.addEventListener('focusout', hideMenu);
}

function initUploadDrawerCloseShortcut() {
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeDrawer();
      closePlayer();
      if (state.viewMode === 'profile') {
        closeProfileSection();
      }
    }
  });
}

initUploadDrawerCloseShortcut();

// ---- 视频播放器 ----
function openPlayer(video) {
  if (!video?.id) {
    spawnToast('当前视频暂无可播放链接', 'warning');
    return;
  }
  sessionStorage.setItem('swingpro_platform_state', JSON.stringify({
    filters: state.filters,
    pagination: state.pagination
  }));
  const target = new URL('/player.html', window.location.origin);
  target.searchParams.set('id', video.id);
  target.searchParams.set('from', 'platform.html');
  window.location.href = target.toString();
}

function closePlayer() {
  if (!dom.playerBackdrop || !dom.playerVideo) return;
  dom.playerBackdrop.classList.remove('show');
  dom.playerVideo.pause();
  dom.playerVideo.removeAttribute('src');
  dom.playerVideo.load();
}

// ---- 个人中心 ----
function initProfileCenter() {
  if (!dom.profileSection) return;

  // Phone edit
  dom.profilePhoneEdit?.addEventListener('click', () => {
    if (dom.profilePhoneForm) {
      dom.profilePhoneForm.reset();
      showFormModal(dom.profilePhoneForm);
    }
  });

  // Password edit
  dom.profilePasswordEdit?.addEventListener('click', () => {
    if (dom.profilePasswordForm) {
      dom.profilePasswordForm.reset();
      showFormModal(dom.profilePasswordForm);
    }
  });

  bindProfileForms();
}

function showFormModal(form) {
  const modal = document.createElement('div');
  modal.className = 'modal-backdrop show';

  const card = document.createElement('div');
  card.className = 'modal-card';

  // Clone the form so we don't move it from its hidden container (or just move it back on close)
  // Better to move it, and move back on close.
  const parent = form.parentElement;
  form.hidden = false;
  card.appendChild(form);

  modal.appendChild(card);
  document.body.appendChild(modal);

  const close = () => {
    form.hidden = true;
    parent.appendChild(form);
    modal.remove();
  };

  // Bind cancel button
  const cancelBtn = form.querySelector('[data-action="cancel"]');
  if (cancelBtn) {
    cancelBtn.onclick = close;
  }

  // Store close function on form for submit handler to use
  form._closeModal = close;
}

function bindProfileForms() {
  // Phone Send OTP
  const sendOtpBtn = dom.profilePhoneForm?.querySelector('#profile-phone-send-otp');
  sendOtpBtn?.addEventListener('click', async () => {
    const input = dom.profilePhoneForm.querySelector('input[name="new_telephone"]');
    const tel = input?.value.trim();
    if (!tel) {
      alert('请先填写手机号');
      return;
    }
    try {
      const res = await apiFetch('/auth/send-code', { method: 'POST', body: { telephone: tel } });
      alert(`验证码已发送${res.mock_otp ? ` (测试: ${res.mock_otp})` : ''}`);
    } catch (err) {
      alert(parseError(err));
    }
  });

  // Phone Submit
  dom.profilePhoneForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(dom.profilePhoneForm);
    const payload = {
      new_telephone: formData.get('new_telephone'),
      otp: formData.get('otp'),
    };
    try {
      await apiFetch('/profile/me/telephone', { method: 'PUT', body: payload });
      alert('手机号已更新，请重新登录');
      logout();
    } catch (err) {
      alert(parseError(err));
    }
  });

  // Password Mode Toggle
  const pwdTabs = dom.profilePasswordForm?.querySelectorAll('input[name="pwd_mode"]');
  pwdTabs?.forEach(tab => {
    tab.addEventListener('change', () => {
      const mode = tab.value;
      const oldDiv = dom.profilePasswordForm.querySelector('#pwd-mode-old');
      const otpDiv = dom.profilePasswordForm.querySelector('#pwd-mode-otp');
      const oldInput = oldDiv?.querySelector('input');
      const otpInput = otpDiv?.querySelector('input');

      if (mode === 'old') {
        oldDiv.hidden = false;
        otpDiv.hidden = true;
        if (oldInput) oldInput.required = true;
        if (otpInput) otpInput.required = false;
        tab.parentElement.classList.add('active');
        dom.profilePasswordForm.querySelector('input[value="otp"]').parentElement.classList.remove('active');
      } else {
        oldDiv.hidden = true;
        otpDiv.hidden = false;
        if (oldInput) oldInput.required = false;
        if (otpInput) otpInput.required = true;
        tab.parentElement.classList.add('active');
        dom.profilePasswordForm.querySelector('input[value="old"]').parentElement.classList.remove('active');
      }
    });
  });

  // Password Send OTP
  const pwdSendOtpBtn = dom.profilePasswordForm?.querySelector('#profile-pwd-send-otp');
  pwdSendOtpBtn?.addEventListener('click', async () => {
    const tel = state.profile.data?.telephone;
    if (!tel) {
      alert('无法获取当前手机号');
      return;
    }
    try {
      const res = await apiFetch('/auth/send-code', { method: 'POST', body: { telephone: tel } });
      alert(`验证码已发送${res.mock_otp ? ` (测试: ${res.mock_otp})` : ''}`);
    } catch (err) {
      alert(parseError(err));
    }
  });

  // Password Submit
  dom.profilePasswordForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = new FormData(dom.profilePasswordForm);
    const mode = formData.get('pwd_mode');
    const newPassword = formData.get('new_password')?.toString().trim();
    const confirmPassword = formData.get('confirm_password')?.toString().trim();
    if (!newPassword) {
      alert('请填写新密码');
      return;
    }
    if (newPassword !== confirmPassword) {
      alert('两次输入的密码不一致');
      return;
    }
    const payload = {
      new_password: newPassword,
    };

    if (mode === 'old') {
      payload.old_password = formData.get('old_password');
    } else {
      payload.otp = formData.get('otp');
      payload.telephone = state.profile.data?.telephone;
    }

    try {
      await apiFetch('/profile/me/password', { method: 'PUT', body: payload });
      alert('密码已更新，请重新登录');
      logout();
    } catch (err) {
      alert(parseError(err));
    }
  });
}

async function openProfileSection() {
  if (!dom.profileSection) {
    window.location.href = '/profile.html';
    return;
  }
  if (state.viewMode !== 'profile') {
    state.previousPane = state.mainPane;
    setAnimatedVisibility(dom.profileSection, true);
    state.viewMode = 'profile';
    document.body.classList.add('profile-open');
    updateMainPaneVisibility();
  }
  try {
    await loadProfileDetails();
  } catch (err) {
    alert(parseError(err));
  }
}

function closeProfileSection(nextPane) {
  if (!dom.profileSection) {
    window.location.href = '/profile.html';
    return;
  }
  if (state.viewMode !== 'profile') return;
  setAnimatedVisibility(dom.profileSection, false);
  document.body.classList.remove('profile-open');
  state.viewMode = 'home';
  const target = nextPane || state.previousPane || state.mainPane || 'videos';
  state.previousPane = null;
  state.mainPane = target || 'videos';
  updateMainPaneVisibility();
  configureManagementVisibility();
}

async function loadProfileDetails() {
  const data = await apiFetch('/profile/me');
  state.profile.data = data;
  renderProfileDetails();
  return data;
}

function renderProfileDetails() {
  const info = state.profile.data || {};
  if (info.id) {
    state.userCache.set(info.id, { username: info.username || null, telephone: info.telephone || null });
  }

  if (dom.profileNickname) dom.profileNickname.textContent = info.username || '未设置昵称';
  if (dom.profilePhone) dom.profilePhone.textContent = info.telephone ? maskTelephone(info.telephone) : '未绑定';
  if (dom.profileRole) dom.profileRole.textContent = getRoleLabel(info.role);
  const profileRoleDetail = document.getElementById('profile-role-detail');
  if (profileRoleDetail) profileRoleDetail.textContent = getRoleLabel(info.role);
  if (dom.profileCreated) dom.profileCreated.textContent = formatProfileTime(info.created_at);

  if (dom.profileAvatarImg) {
    dom.profileAvatarImg.src = info.avatar_url || DEFAULT_AVATAR;
  }

  if (state.auth) {
    state.auth.telephone = info.telephone;
    if (info.role) state.auth.role = info.role;
    if (info.avatar_url) state.auth.avatar_url = info.avatar_url;
    saveAuth(state.auth);
    if (!ensureAllowedRole()) return;
    updateNavUserDisplay();
    updateMainPaneVisibility();
    configureManagementVisibility();
  }
}


function formatProfileTime(value) {
  return formatDateTime(value) || '—';
}

function resolveMediaUrl(path) {
  if (!path) return null;
  if (/^https?:\/\//i.test(path)) return path;
  // Convert absolute file path under VIDEO_ROOT to /media URL
  const videoRoot = localStorage.getItem('videoRootCache');
  let base = state.apiBase || '';
  if (base.endsWith('/')) base = base.slice(0, -1);
  if (path.startsWith('/')) {
    const storedRoot = window.__VIDEO_ROOT__ || videoRoot;
    if (storedRoot && path.startsWith(storedRoot)) {
      const rel = path.substring(storedRoot.length).replace(/^\//, '');
      return `${base}/media/${rel}`;
    }
  }
  return null;
}

function maskDisplayName(auth) {
  if (auth?.telephone && auth.telephone.length >= 7) {
    return auth.telephone.replace(/(\d{3})\d{4}(\d{4})/, '$1****$2');
  }
  if (auth?.userId) {
    return auth.userId.slice(0, 3) + '***';
  }
  return '用户';
}

function redirectToLogin() {
  if (!LOGIN_URL) return;
  const target = LOGIN_URL;
  const isAbsolute = /^https?:\/\//i.test(target);
  if (isAbsolute && window.location.href === target) return;
  if (!isAbsolute && (window.location.pathname === target || window.location.pathname.endsWith(target))) return;
  window.location.replace(target);
}

// ==========================================
// Stats & Monitoring
// ==========================================

function formatDateInput(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function updateStatsPeriodButtons() {
  const days = state.management.statsDays || 7;
  if (!dom.statsPeriodButtons) return;
  dom.statsPeriodButtons.forEach((btn) => {
    const d = Number(btn.dataset.statsDays || 0);
    btn.classList.toggle('active', d === days);
  });
}

function initPortraitHoverCard() {
  const bindTrigger = (trigger) => {
    if (!trigger) return;
    const key = trigger.dataset.portraitKey;
    if (!key) return;
    trigger.addEventListener('mouseenter', () => showPortraitHoverCard(trigger, key));
    trigger.addEventListener('mouseleave', scheduleHidePortraitHoverCard);
    trigger.addEventListener('click', (event) => {
      event.preventDefault();
      showPortraitHoverCard(trigger, key, true);
    });
  };

  bindTrigger(dom.overviewCardHigh);
  bindTrigger(dom.overviewCardMedium);
  bindTrigger(dom.overviewCardLight);
  bindTrigger(dom.overviewCardSilent);

  dom.portraitHoverCard?.addEventListener('mouseenter', () => {
    if (portraitHoverHideTimer) {
      clearTimeout(portraitHoverHideTimer);
      portraitHoverHideTimer = null;
    }
  });
  dom.portraitHoverCard?.addEventListener('mouseleave', hidePortraitHoverCard);
  dom.portraitHoverCard?.addEventListener('click', (event) => {
    const btn = event.target.closest('button[data-action="show-all-portrait"]');
    if (!btn) return;
    event.preventDefault();
    const key = btn.dataset.key;
    if (!key || !portraitHoverActiveTrigger) return;
    showPortraitHoverCard(portraitHoverActiveTrigger, key, true);
  });
}

function showPortraitHoverCard(trigger, key, showAll = false) {
  if (!dom.portraitHoverCard || !dom.userPortraitSection) return;
  if (portraitHoverHideTimer) {
    clearTimeout(portraitHoverHideTimer);
    portraitHoverHideTimer = null;
  }

  portraitHoverActiveKey = key;
  portraitHoverActiveTrigger = trigger;

  const list = Array.isArray(state.management.portraitUsers?.[key]) ? state.management.portraitUsers[key] : [];
  const isSilent = key === 'silent';
  const titleMap = {
    high: '高活跃用户明细（15天）',
    medium: '中活跃用户明细（15天）',
    light: '低活跃用户明细（15天）',
    silent: '沉默用户明细（15天）',
  };
  const title = titleMap[key] || '用户明细';

  if (!list.length) {
    dom.portraitHoverCard.innerHTML = `<div class="portrait-hover-title">${escapeHtml(title)}</div><div class="portrait-empty">暂无用户</div>`;
  } else {
    const visibleItems = showAll ? list : list.slice(0, 5);
    const rows = visibleItems.map((item) => {
      const displayName = item.username || item.telephone || '未知用户';
      const countText = isSilent ? '' : `<span class="portrait-count">${Number(item.upload_count_window ?? 0)} 条</span>`;
      return `
        <li>
          <img class="management-avatar" src="${escapeHtml(item.avatar_url || DEFAULT_AVATAR)}" alt="${escapeHtml(displayName)}" />
          <span class="portrait-name">${escapeHtml(displayName)}</span>
          ${countText}
        </li>
      `;
    }).join('');
    const action = (!showAll && list.length > 5)
      ? `<div class="portrait-hover-actions"><button type="button" class="btn btn-ghost btn-compact" data-action="show-all-portrait" data-key="${escapeHtml(key)}">查看全部（${list.length}）</button></div>`
      : '';
    dom.portraitHoverCard.innerHTML = `<div class="portrait-hover-title">${escapeHtml(title)}</div><ul class="portrait-list">${rows}</ul>${action}`;
  }

  const sectionRect = dom.userPortraitSection.getBoundingClientRect();
  const triggerRect = trigger.getBoundingClientRect();
  const left = Math.max(8, triggerRect.left - sectionRect.left);
  const top = Math.max(12, triggerRect.bottom - sectionRect.top + 8);

  dom.portraitHoverCard.style.left = `${left}px`;
  dom.portraitHoverCard.style.top = `${top}px`;
  dom.portraitHoverCard.hidden = false;
}

function scheduleHidePortraitHoverCard() {
  if (portraitHoverHideTimer) {
    clearTimeout(portraitHoverHideTimer);
  }
  portraitHoverHideTimer = setTimeout(() => {
    hidePortraitHoverCard();
  }, 140);
}

function hidePortraitHoverCard() {
  if (portraitHoverHideTimer) {
    clearTimeout(portraitHoverHideTimer);
    portraitHoverHideTimer = null;
  }
  portraitHoverActiveKey = null;
  portraitHoverActiveTrigger = null;
  if (dom.portraitHoverCard) {
    dom.portraitHoverCard.hidden = true;
  }
}

function handleUploadUserRowClick(event) {
  const row = event.target.closest('tr.upload-user-row');
  if (!row) return;
  const userId = row.dataset.userId;
  if (!userId) return;

  const username = row.dataset.username || '该用户';
  const endDate = new Date();
  const startDate = new Date(endDate);
  startDate.setDate(endDate.getDate() - 14);

  state.filters.ownerId = userId;
  state.filters.ownerLabel = username;
  state.filters.ownerKeyword = username;
  state.filters.wechatKeyword = '';
  state.filters.dateStart = formatDateInput(startDate);
  state.filters.dateEnd = formatDateInput(endDate);
  state.pagination.page = 1;

  syncAdminFilterInputs();
  updateAdminOwnerChip();
  hideOwnerSuggestions();
  hideWechatSuggestions();
  setMainPane('videos');
  loadVideos();
  spawnToast(`已切换到 ${username} 的近期视频`, 'info');
}

async function loadSystemStats() {
  if (!dom.statUsers || !dom.statVideos || !dom.statTodayVideos) return;
  try {
    hidePortraitHoverCard();
    updateStatsPeriodButtons();
    const selectedDays = state.management.statsDays || 7;
    const data = await apiFetch(`/admin/system/overview?days=${selectedDays}`);
    const windowDays = Number(data?.window_days || selectedDays || 7);
    state.management.statsDays = [7, 15, 30].includes(windowDays) ? windowDays : 7;
    updateStatsPeriodButtons();

    dom.statUsers.textContent = data?.users?.total ?? '--';
    dom.statVideos.textContent = data?.videos?.total ?? '--';
    if (dom.statActiveUsers) dom.statActiveUsers.textContent = data?.users?.active ?? '--';
    if (dom.statTodayUsers) dom.statTodayUsers.textContent = data?.today?.new_users ?? '--';
    dom.statTodayVideos.textContent = data?.today?.new_videos ?? '--';
    if (dom.statTodayOnline) dom.statTodayOnline.textContent = data?.today?.online_users ?? '--';

    const todayTop = data?.today?.top_uploader || null;
    if (dom.statTodayTopSummary) {
      dom.statTodayTopSummary.textContent = todayTop
        ? `${todayTop.username || '未知用户'}（${Number(todayTop.upload_count ?? 0)} 条）`
        : '--';
    }

    const upload = data?.video_details?.upload || {};
    if (dom.overviewUploadTotal7d) dom.overviewUploadTotal7d.textContent = upload.total_window ?? upload.total_7d ?? '--';
    if (dom.overviewUploadUsers7d) dom.overviewUploadUsers7d.textContent = upload.upload_users_window ?? upload.upload_users_7d ?? '--';
    if (dom.overviewUploadAvg7d) dom.overviewUploadAvg7d.textContent = upload.avg_daily_window ?? upload.avg_daily_7d ?? '--';
    if (dom.overviewUploadTotalToday) dom.overviewUploadTotalToday.textContent = upload.total_today ?? '--';

    const activityLayers = data?.users?.activity_layers || {};
    const layerItems = Array.isArray(activityLayers?.items) ? activityLayers.items : [];
    const getLayer = (key) => layerItems.find((item) => item.key === key);
    if (dom.overviewLayerHigh) dom.overviewLayerHigh.textContent = getLayer('high')?.count ?? '--';
    if (dom.overviewLayerMedium) dom.overviewLayerMedium.textContent = getLayer('medium')?.count ?? '--';
    if (dom.overviewLayerLight) dom.overviewLayerLight.textContent = getLayer('light')?.count ?? '--';
    if (dom.overviewLayerSilent) dom.overviewLayerSilent.textContent = getLayer('silent')?.count ?? '--';

    state.management.portraitUsers = {
      high: Array.isArray(activityLayers?.high_users) ? activityLayers.high_users : [],
      medium: Array.isArray(activityLayers?.medium_users) ? activityLayers.medium_users : [],
      light: Array.isArray(activityLayers?.light_users) ? activityLayers.light_users : [],
      silent: Array.isArray(activityLayers?.silent_users) ? activityLayers.silent_users : [],
    };

    renderUploadTrendChart(data?.video_details?.trend || data?.video_details?.trend_7d || [], windowDays);
    renderUploadUserTable(data?.video_details?.user_upload_rows || []);
  } catch (err) {
    console.error('[Stats] loadSystemStats error', err);
    spawnToast('加载业务概览失败', 'error');
  }
}

function renderUploadUserTable(items) {
  if (!dom.uploadUserTableBody) return;
  dom.uploadUserTableBody.innerHTML = '';
  if (!Array.isArray(items) || items.length === 0) {
    dom.uploadUserTableBody.innerHTML = '<tr><td colspan="7" class="empty-cell">暂无上传用户数据</td></tr>';
    return;
  }

  items.forEach((item) => {
    const tr = document.createElement('tr');
    const displayName = item.username || item.telephone || '-';
    if (item.user_id) {
      tr.classList.add('upload-user-row');
      tr.dataset.userId = String(item.user_id);
      tr.dataset.username = displayName;
    }

    tr.innerHTML = `
      <td>${item.rank ?? '-'}</td>
      <td>
        <div class="management-info-col">
          <img class="management-avatar" src="${escapeHtml(item.avatar_url || DEFAULT_AVATAR)}" alt="${escapeHtml(displayName)}" />
          <span>${escapeHtml(displayName)}</span>
        </div>
      </td>
      <td>${item.upload_total ?? 0}</td>
      <td>${item.front_count ?? 0}</td>
      <td>${item.side_count ?? 0}</td>
      <td>${item.top_count ?? 0}</td>
      <td>${item.pro_count ?? 0}</td>
    `;
    dom.uploadUserTableBody.appendChild(tr);
  });
}

function renderUploadTrendChart(items, days) {
  if (!dom.uploadTrendChart) return;
  const points = Array.isArray(items) ? items : [];
  if (dom.uploadTrendTooltip) dom.uploadTrendTooltip.hidden = true;
  if (!points.length) {
    dom.uploadTrendChart.innerHTML = '<text x="50%" y="50%" text-anchor="middle" fill="#94a3b8" font-size="14">暂无趋势数据</text>';
    if (dom.uploadTrendLegend) dom.uploadTrendLegend.textContent = '--';
    return;
  }

  const width = 760;
  const height = 240;
  const padLeft = 48;
  const padRight = 24;
  const padTop = 20;
  const padBottom = 36;
  const plotWidth = width - padLeft - padRight;
  const plotHeight = height - padTop - padBottom;

  const uploadValues = points.map((p) => Number(p.upload_count ?? p.count ?? 0));
  const maxVal = Math.max(...uploadValues, 1);

  const niceCeil = (value) => {
    if (!Number.isFinite(value) || value <= 0) return 1;
    const exponent = Math.pow(10, Math.floor(Math.log10(value)));
    const fraction = value / exponent;
    let niceFraction = 1;
    if (fraction <= 1) niceFraction = 1;
    else if (fraction <= 2) niceFraction = 2;
    else if (fraction <= 5) niceFraction = 5;
    else niceFraction = 10;
    return niceFraction * exponent;
  };

  const axisMax = niceCeil(maxVal);
  const stepX = points.length > 1 ? plotWidth / (points.length - 1) : 0;
  const toX = (idx) => padLeft + idx * stepX;
  const toY = (val) => padTop + plotHeight - (val / axisMax) * plotHeight;

  const tickCount = 4;
  const grid = Array.from({ length: tickCount + 1 }, (_, i) => {
    const ratio = i / tickCount;
    const y = padTop + plotHeight - ratio * plotHeight;
    const value = Math.round(axisMax * ratio);
    return `
      <line x1="${padLeft}" y1="${y}" x2="${width - padRight}" y2="${y}" stroke="rgba(148,163,184,0.25)" stroke-width="1" />
      <text x="${padLeft - 10}" y="${y + 4}" text-anchor="end" fill="#94a3b8" font-size="11">${value}</text>
    `;
  }).join('');

  const uploadPolylinePoints = points
    .map((p, idx) => `${toX(idx)},${toY(Number(p.upload_count ?? p.count ?? 0))}`)
    .join(' ');

  const areaPath = `${uploadPolylinePoints} ${toX(points.length - 1)},${padTop + plotHeight} ${toX(0)},${padTop + plotHeight}`;

  let labelStep = 1;
  if (points.length > 20) labelStep = 4;
  else if (points.length > 12) labelStep = 2;

  const dots = points.map((p, idx) => {
    const x = toX(idx);
    const uploadY = toY(Number(p.upload_count ?? p.count ?? 0));
    const dateText = String(p.date || '').slice(5);
    const showDate = idx % labelStep === 0 || idx === points.length - 1;
    return `
      <circle class="trend-point" data-index="${idx}" data-date="${p.date || ''}" data-count="${Number(p.upload_count ?? p.count ?? 0)}" cx="${x}" cy="${uploadY}" r="4" fill="#10b981" />
      ${showDate ? `<text x="${x}" y="${height - 12}" text-anchor="middle" fill="#94a3b8" font-size="11">${dateText}</text>` : ''}
    `;
  }).join('');

  dom.uploadTrendChart.innerHTML = `
    <rect x="0" y="0" width="100%" height="100%" fill="transparent" />
    ${grid}
    <polygon points="${areaPath}" fill="rgba(16,185,129,0.14)" />
    <polyline points="${uploadPolylinePoints}" fill="none" stroke="#10b981" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
    ${dots}
  `;

  const tooltip = dom.uploadTrendTooltip;
  const chartWrap = dom.uploadTrendChart.closest('.trend-card');
  const hideTooltip = () => {
    if (tooltip) tooltip.hidden = true;
  };
  dom.uploadTrendChart.onmouseleave = hideTooltip;
  dom.uploadTrendChart.querySelectorAll('.trend-point').forEach((el) => {
    el.addEventListener('mouseenter', (evt) => {
      if (!tooltip || !chartWrap) return;
      const date = el.getAttribute('data-date') || '-';
      const count = Number(el.getAttribute('data-count') || 0);
      tooltip.innerHTML = `<strong>${escapeHtml(date)}</strong><span>上传量：${count}</span>`;
      const wrapRect = chartWrap.getBoundingClientRect();
      const maxX = wrapRect.width - 160;
      const x = Math.min(Math.max(8, evt.clientX - wrapRect.left + 10), Math.max(8, maxX));
      const y = evt.clientY - wrapRect.top - 12;
      tooltip.style.left = `${x}px`;
      tooltip.style.top = `${Math.max(8, y)}px`;
      tooltip.hidden = false;
    });
    el.addEventListener('mousemove', (evt) => {
      if (!tooltip || !chartWrap) return;
      const wrapRect = chartWrap.getBoundingClientRect();
      const maxX = wrapRect.width - 160;
      const x = Math.min(Math.max(8, evt.clientX - wrapRect.left + 10), Math.max(8, maxX));
      const y = evt.clientY - wrapRect.top - 12;
      tooltip.style.left = `${x}px`;
      tooltip.style.top = `${Math.max(8, y)}px`;
    });
    el.addEventListener('mouseleave', hideTooltip);
  });

  if (dom.uploadTrendLegend) {
    const uploadTotal = uploadValues.reduce((acc, n) => acc + n, 0);
    const uploadAvg = points.length ? (uploadTotal / points.length).toFixed(1) : '0.0';
    dom.uploadTrendLegend.textContent = `近${days || points.length}天：上传总量 ${uploadTotal}，日均 ${uploadAvg}`;
  }
}

async function loadSystemChecks() {
  if (!dom.systemCheckTableBody || !dom.systemAnomalyTableBody) return;
  try {
    const data = await apiFetch('/admin/system/checks');
    const checks = Array.isArray(data?.checks) ? data.checks : [];
    const anomalies = Array.isArray(data?.anomalies) ? data.anomalies : [];
    state.management.systemChecks = checks;
    state.management.systemAnomalies = anomalies;

    renderSystemCheckSummary(checks, anomalies);
    renderSystemAnomalyCategoryOptions(anomalies);
    syncSystemCheckFiltersFromDom();
    applySystemCheckFilters();

    if (dom.systemCheckGeneratedAt) {
      const generated = formatDateTime(data?.generated_at) || '--';
      const windowHours = Number(data?.window_hours || 24);
      dom.systemCheckGeneratedAt.textContent = `更新时间：${generated} · 统计窗口：${windowHours}h`;
    }
  } catch (err) {
    console.error('[Stats] loadSystemChecks error', err);
    spawnToast('加载系统检查失败', 'error');
  }
}

function getSystemCheckStatusMeta(status) {
  if (status === 'ok') return { label: '正常', className: 'check-ok', priority: 2 };
  if (status === 'warn') return { label: '警告', className: 'check-warn', priority: 1 };
  return { label: '异常', className: 'check-error', priority: 0 };
}

function normalizeText(value) {
  return String(value || '').trim().toLowerCase();
}

function syncSystemCheckFiltersFromDom() {
  state.management.systemCheckFilters.status = dom.systemCheckStatusFilter?.value || 'all';
  state.management.systemCheckFilters.keyword = normalizeText(dom.systemCheckKeyword?.value || '');
  state.management.systemCheckFilters.anomalyCategory = dom.systemAnomalyCategoryFilter?.value || 'all';
  state.management.systemCheckFilters.anomalyKeyword = normalizeText(dom.systemAnomalyKeyword?.value || '');
}

function handleSystemCheckFilterChanged() {
  if (systemCheckFilterTimer) {
    clearTimeout(systemCheckFilterTimer);
  }
  systemCheckFilterTimer = setTimeout(() => {
    syncSystemCheckFiltersFromDom();
    applySystemCheckFilters();
  }, 120);
}

function renderSystemCheckSummary(checks, anomalies) {
  const list = Array.isArray(checks) ? checks : [];
  const total = list.length;
  const okCount = list.filter((item) => item?.status === 'ok').length;
  const warnCount = list.filter((item) => item?.status === 'warn').length;
  const errorCount = list.filter((item) => item?.status !== 'ok' && item?.status !== 'warn').length;
  const anomalyTotal = Array.isArray(anomalies) ? anomalies.length : 0;

  if (dom.systemCheckTotal) dom.systemCheckTotal.textContent = String(total);
  if (dom.systemCheckOk) dom.systemCheckOk.textContent = String(okCount);
  if (dom.systemCheckWarn) dom.systemCheckWarn.textContent = String(warnCount);
  if (dom.systemCheckError) dom.systemCheckError.textContent = String(errorCount);
  if (dom.systemAnomalyTotal) dom.systemAnomalyTotal.textContent = String(anomalyTotal);
}

function renderSystemAnomalyCategoryOptions(items) {
  if (!dom.systemAnomalyCategoryFilter) return;
  const categories = Array.from(new Set((Array.isArray(items) ? items : [])
    .map((item) => String(item?.category || '').trim())
    .filter(Boolean)));
  const current = dom.systemAnomalyCategoryFilter.value || 'all';
  dom.systemAnomalyCategoryFilter.innerHTML = '';

  const allOption = document.createElement('option');
  allOption.value = 'all';
  allOption.textContent = '全部分类';
  dom.systemAnomalyCategoryFilter.appendChild(allOption);

  categories.forEach((category) => {
    const opt = document.createElement('option');
    opt.value = category;
    opt.textContent = category;
    dom.systemAnomalyCategoryFilter.appendChild(opt);
  });

  dom.systemAnomalyCategoryFilter.value = categories.includes(current) || current === 'all' ? current : 'all';
}

function applySystemCheckFilters() {
  const checksRaw = Array.isArray(state.management.systemChecks) ? state.management.systemChecks : [];
  const anomaliesRaw = Array.isArray(state.management.systemAnomalies) ? state.management.systemAnomalies : [];
  const filters = state.management.systemCheckFilters || {};

  let checks = [...checksRaw];
  if (filters.status && filters.status !== 'all') {
    checks = checks.filter((item) => String(item?.status || '') === filters.status);
  }
  if (filters.keyword) {
    checks = checks.filter((item) => {
      const haystack = [item?.name, item?.value, item?.detail, item?.key].map((x) => normalizeText(x)).join(' ');
      return haystack.includes(filters.keyword);
    });
  }
  checks.sort((a, b) => {
    const sa = getSystemCheckStatusMeta(a?.status).priority;
    const sb = getSystemCheckStatusMeta(b?.status).priority;
    if (sa !== sb) return sa - sb;
    return String(a?.name || '').localeCompare(String(b?.name || ''), 'zh-CN');
  });

  let anomalies = [...anomaliesRaw];
  if (filters.anomalyCategory && filters.anomalyCategory !== 'all') {
    anomalies = anomalies.filter((item) => String(item?.category || '') === filters.anomalyCategory);
  }
  if (filters.anomalyKeyword) {
    anomalies = anomalies.filter((item) => {
      const haystack = [
        item?.action,
        item?.category,
        item?.user_telephone,
        item?.user_role,
        item?.ip,
        item?.error,
      ].map((x) => normalizeText(x)).join(' ');
      return haystack.includes(filters.anomalyKeyword);
    });
  }

  renderSystemCheckTable(checks);
  renderSystemAnomalyTable(anomalies);

  if (dom.systemAnomalyTip) {
    dom.systemAnomalyTip.textContent = `当前筛选：${anomalies.length} / ${anomaliesRaw.length} 条`;
  }
}

function renderSystemCheckTable(checks) {
  if (!dom.systemCheckTableBody) return;
  dom.systemCheckTableBody.innerHTML = '';
  if (!checks.length) {
    dom.systemCheckTableBody.innerHTML = '<tr><td colspan="4" class="empty-cell">当前筛选条件下暂无检查数据</td></tr>';
    return;
  }
  checks.forEach((item) => {
    const tr = document.createElement('tr');
    const meta = getSystemCheckStatusMeta(item.status);
    if (item.status === 'warn') tr.classList.add('check-row-warn');
    if (item.status !== 'warn' && item.status !== 'ok') tr.classList.add('check-row-error');
    const latestErrorLog = item.latest_error_log_time ? `最近错误日志：${formatDateTime(item.latest_error_log_time) || item.latest_error_log_time}` : '';
    const detailText = [item.detail, latestErrorLog].filter(Boolean).join('；');
    tr.innerHTML = `
      <td>${escapeHtml(item.name || '-')}</td>
      <td><span class="check-badge ${meta.className}">${meta.label}</span></td>
      <td>${escapeHtml(String(item.value ?? '-'))}</td>
      <td>${escapeHtml(detailText || '-')}</td>
    `;
    dom.systemCheckTableBody.appendChild(tr);
  });
}

function renderSystemAnomalyTable(items) {
  if (!dom.systemAnomalyTableBody) return;
  dom.systemAnomalyTableBody.innerHTML = '';
  if (!items.length) {
    dom.systemAnomalyTableBody.innerHTML = '<tr><td colspan="5" class="empty-cell">当前筛选条件下无异常记录</td></tr>';
    return;
  }
  items.forEach((item) => {
    const tr = document.createElement('tr');
    const userDetail = [item?.user_role, item?.ip].filter(Boolean).join(' · ');
    tr.innerHTML = `
      <td>${formatDateTime(item.time) || '-'}</td>
      <td>${escapeHtml(item.category || '-')}</td>
      <td>${escapeHtml(item.action || '-')}</td>
      <td>
        <div>${escapeHtml(item.user_telephone || '-')}</div>
        <div class="text-xs text-muted">${escapeHtml(userDetail || '-')}</div>
      </td>
      <td class="anomaly-error-cell">${escapeHtml(item.error || '-')}</td>
    `;
    dom.systemAnomalyTableBody.appendChild(tr);
  });
}

function renderActivityTable(tbody, items, isSensitive) {
  tbody.innerHTML = '';
  if (!items || items.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-cell">暂无记录</td></tr>';
    return;
  }
  items.forEach(item => {
    const tr = document.createElement('tr');
    const date = new Date(item.time).toLocaleString('zh-CN');
    const statusClass = item.success ? 'text-success' : 'text-error';
    const statusText = item.success ? '成功' : '失败';

    // Sensitive table has slightly different columns in HTML: Time, User, Action, Detail, IP
    // Recent table: Time, Category, Action, User, Status

    if (isSensitive) {
       tr.innerHTML = `
        <td>${date}</td>
        <td>
          <div>${item.user_telephone || '-'}</div>
          <div class="text-xs text-muted">${item.user_role || ''}</div>
        </td>
        <td>${item.action}</td>
        <td>
           ${item.detail ? JSON.stringify(item.detail).slice(0, 50) : '-'}
           ${item.error ? `<div class="text-xs text-error">${item.error}</div>` : ''}
        </td>
        <td>${item.ip || '-'}</td>
      `;
    } else {
      tr.innerHTML = `
        <td>${date}</td>
        <td>${item.category || '-'}</td>
        <td>${item.action}</td>
        <td>
          <div>${item.user_telephone || '-'}</div>
        </td>
        <td>
          <span class="${statusClass}">${statusText}</span>
          ${item.error ? `<div class="text-xs text-error">${item.error}</div>` : ''}
        </td>
      `;
    }
    tbody.appendChild(tr);
  });
}
