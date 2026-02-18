// ===== State =====
var state = {
  activeView: 'catalog',       // 'catalog' or 'preview'
  activeGoal: null,
  searchPattern: null,
  searchText: '',
  dirty: {hierarchy: true, files: true, stats: true},
  previewMode: 'hook-read-standard',
  fileDetailPath: null
};

function renderAll() {
  if (state.dirty.hierarchy) {
    renderHierarchy(document.getElementById('hierarchyContent'));
  }
  if (state.dirty.files) {
    var filesEl = document.getElementById('filesContent');
    if (state.fileDetailPath) {
      renderFileDetail(state.fileDetailPath, filesEl);
    } else {
      renderFiles(filesEl);
    }
  }
  if (state.dirty.stats) {
    renderStats(document.getElementById('statsContent'));
  }
}

function switchView(view) {
  state.activeView = view;
  var catalogEl = document.getElementById('viewCatalog');
  var previewEl = document.getElementById('viewPreview');
  var sidebarEl = document.getElementById('sidebar');
  var searchEl = document.getElementById('searchBoxWrap');
  var tabs = document.querySelectorAll('.view-tab');

  for (var i = 0; i < tabs.length; i++) {
    tabs[i].classList.toggle('active', tabs[i].getAttribute('data-view') === view);
  }

  if (view === 'catalog') {
    catalogEl.classList.remove('view-hidden');
    previewEl.classList.add('view-hidden');
    sidebarEl.style.display = '';
    searchEl.style.display = '';
  } else {
    catalogEl.classList.add('view-hidden');
    previewEl.classList.remove('view-hidden');
    sidebarEl.style.display = 'none';
    searchEl.style.display = 'none';
  }
}

// ===== Top counts =====
function renderTopCounts() {
  var el = document.getElementById('topCounts');
  el.innerHTML = '<span class="c-goal">' + goalNodes.length + 'G</span>' +
    '<span class="c-exp">' + expNodes.length + 'E</span>' +
    '<span class="c-facet">' + facetNodes.length + 'F</span>';
}

// ===== Sidebar =====
function renderSidebar() {
  var sb = document.getElementById('sidebar');
  var html = '<div class="goal-card' + (state.activeGoal === null ? ' active' : '') +
    '" data-goal="all">All Goals</div>';
  for (var i = 0; i < goalNodes.length; i++) {
    var g = goalNodes[i];
    var exps = getChildren(g.id);
    var fcount = 0;
    for (var j = 0; j < exps.length; j++) {
      fcount += getChildren(exps[j].id).length;
    }
    var isActive = state.activeGoal === g.id;
    var matchHtml = '';
    if (state.searchPattern) {
      var mc = countMatchesUnderGoal(g.id);
      if (mc > 0) matchHtml = '<span class="match-count">' + mc + '</span>';
    }
    html += '<div class="goal-card' + (isActive ? ' active' : '') + '" data-goal="' + g.id + '">' +
      matchHtml +
      '<div class="gid">' + g.id + '</div>' +
      '<div class="gname">' + esc(g.text) + '</div>' +
      '<div class="gmeta">' + exps.length + ' exp, ' + fcount + ' facets' +
      (g.priority ? ' &middot; P' + g.priority : '') + '</div>' +
      '</div>';
  }
  sb.innerHTML = html;

  // Attach click handlers via event delegation
  sb.onclick = function(e) {
    var card = e.target.closest('.goal-card');
    if (!card) return;
    var gid = card.getAttribute('data-goal');
    state.activeGoal = gid === 'all' ? null : gid;
    state.dirty.hierarchy = true;
    state.dirty.files = true;
    state.dirty.stats = true;
    renderSidebar();
    renderAll();
  };
}

// ===== Search =====
var searchTimeout = null;
function setupSearch() {
  var input = document.getElementById('searchInput');
  input.addEventListener('input', function() {
    clearTimeout(searchTimeout);
    var val = this.value.trim();
    searchTimeout = setTimeout(function() {
      if (!val) {
        state.searchPattern = null;
        state.searchText = '';
        input.classList.remove('invalid');
      } else {
        try {
          state.searchPattern = new RegExp(val, 'gi');
          state.searchText = val;
          input.classList.remove('invalid');
        } catch(e) {
          input.classList.add('invalid');
          return;
        }
      }
      state.dirty.hierarchy = true;
      state.dirty.files = true;
      state.dirty.stats = true;
      renderSidebar();
      renderAll();
    }, 200);
  });
}
