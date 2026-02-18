// ===== Panel: Stats =====
function renderBarChart(title, items, maxVal, width) {
  width = width || 400;
  var barH = 20, gap = 4, labelW = 140, valW = 40;
  var chartW = width - labelW - valW - 20;
  var h = items.length * (barH + gap) + 10;
  var svg = '<svg width="' + width + '" height="' + h + '">';
  for (var i = 0; i < items.length; i++) {
    var y = i * (barH + gap) + 2;
    var bw = maxVal > 0 ? (items[i].value / maxVal) * chartW : 0;
    var labelHtml = items[i].fileLink
      ? '' // skip SVG text; we'll overlay HTML
      : '<text x="0" y="' + (y + 14) + '" font-size="11" fill="#495057">' + esc(items[i].label) + '</text>';
    svg += labelHtml;
    svg += '<rect x="' + labelW + '" y="' + y + '" width="' + bw + '" height="' + barH + '" rx="2" fill="' + (items[i].color || '#0d6efd') + '" opacity="0.8"/>';
    svg += '<text x="' + (labelW + chartW + 4) + '" y="' + (y + 14) + '" font-size="11" fill="#495057">' + items[i].value + '</text>';
  }
  svg += '</svg>';
  return '<div class="bar-chart"><div class="chart-title">' + esc(title) + '</div>' + svg + '</div>';
}

function renderStats(container) {
  // Scope to active goal if selected
  var scopedFacets, scopedExps, scopedGoals;
  if (state.activeGoal) {
    scopedGoals = [nodeMap[state.activeGoal]];
    scopedExps = [];
    scopedFacets = [];
    function collectScoped(nid) {
      var n = nodeMap[nid];
      if (!n) return;
      if (n.type === 'expectation') scopedExps.push(n);
      if (n.type === 'facet') scopedFacets.push(n);
      var kids = childrenMap[nid] || [];
      for (var i = 0; i < kids.length; i++) collectScoped(kids[i]);
    }
    collectScoped(state.activeGoal);
  } else {
    scopedGoals = goalNodes;
    scopedExps = expNodes;
    scopedFacets = facetNodes;
  }

  var html = '<div class="stat-cards">';
  html += '<div class="stat-card sc-goal"><div class="num">' + scopedGoals.length + '</div><div class="lbl">Goals</div></div>';
  html += '<div class="stat-card sc-exp"><div class="num">' + scopedExps.length + '</div><div class="lbl">Expectations</div></div>';
  html += '<div class="stat-card sc-facet"><div class="num">' + scopedFacets.length + '</div><div class="lbl">Facets</div></div>';
  html += '</div>';

  // Status distribution
  var passing = 0, failing = 0, untested = 0;
  for (var i = 0; i < scopedFacets.length; i++) {
    var s = scopedFacets[i].status || 'untested';
    if (s === 'passing') passing++;
    else if (s === 'failing') failing++;
    else untested++;
  }
  var maxStatus = Math.max(passing, failing, untested, 1);
  html += renderBarChart('Status Distribution', [
    {label: 'Passing', value: passing, color: '#198754'},
    {label: 'Failing', value: failing, color: '#dc3545'},
    {label: 'Untested', value: untested, color: '#6c757d'}
  ], maxStatus);

  // Label frequency
  var labelCounts = {};
  for (var j = 0; j < scopedExps.length; j++) {
    var labels = scopedExps[j].labels || [];
    for (var k = 0; k < labels.length; k++) {
      labelCounts[labels[k]] = (labelCounts[labels[k]] || 0) + 1;
    }
  }
  for (var jg = 0; jg < scopedGoals.length; jg++) {
    var glabels = scopedGoals[jg].labels || [];
    for (var kg = 0; kg < glabels.length; kg++) {
      labelCounts[glabels[kg]] = (labelCounts[glabels[kg]] || 0) + 1;
    }
  }
  var labelItems = [];
  for (var lb in labelCounts) labelItems.push({label: lb, value: labelCounts[lb], color: '#0d6efd'});
  labelItems.sort(function(a, b) { return b.value - a.value; });
  var maxLabel = labelItems.length > 0 ? labelItems[0].value : 1;
  if (labelItems.length > 0) {
    html += renderBarChart('Label Frequency', labelItems, maxLabel);
  }

  // Per-goal completion bars
  html += '<div class="chart-title" style="margin-top:16px">Goal Completion (% facets passing)</div>';
  var completionGoals = state.activeGoal ? [nodeMap[state.activeGoal]] : goalNodes;
  for (var cg = 0; cg < completionGoals.length; cg++) {
    var goal = completionGoals[cg];
    var gFacets = [];
    function collectGoalFacets(nid) {
      var n = nodeMap[nid];
      if (!n) return;
      if (n.type === 'facet') gFacets.push(n);
      var kids = childrenMap[nid] || [];
      for (var ci = 0; ci < kids.length; ci++) collectGoalFacets(kids[ci]);
    }
    collectGoalFacets(goal.id);
    var gPassing = 0;
    for (var gf = 0; gf < gFacets.length; gf++) {
      if ((gFacets[gf].status || 'untested') === 'passing') gPassing++;
    }
    var pct = gFacets.length > 0 ? Math.round(gPassing / gFacets.length * 100) : 0;
    var barColor = pct === 100 ? '#198754' : pct > 0 ? '#ffc107' : '#e9ecef';
    html += '<div class="completion-bar-wrap">';
    html += '<div class="completion-bar-label" title="' + esc(goal.text) + '">' + goal.id + ' ' + esc(goal.text) + '</div>';
    html += '<div class="completion-bar-outer"><div class="completion-bar-inner" style="width:' + pct + '%;background:' + barColor + '"></div></div>';
    html += '<div class="completion-bar-pct">' + pct + '%</div>';
    html += '</div>';
  }

  // Files with most facets — use file links
  var fileFacetCounts = [];
  for (var ff in derived.file_map) {
    fileFacetCounts.push({label: ff, value: derived.file_map[ff].length, color: '#495057'});
  }
  fileFacetCounts.sort(function(a, b) { return b.value - a.value; });
  if (fileFacetCounts.length > 10) fileFacetCounts = fileFacetCounts.slice(0, 10);
  var maxFileFacets = fileFacetCounts.length > 0 ? fileFacetCounts[0].value : 1;
  if (fileFacetCounts.length > 0) {
    html += '<div class="chart-title" style="margin-top:16px">Top Files by Facet Count</div>';
    for (var tfi = 0; tfi < fileFacetCounts.length; tfi++) {
      var item = fileFacetCounts[tfi];
      var bPct = maxFileFacets > 0 ? Math.round(item.value / maxFileFacets * 100) : 0;
      html += '<div class="completion-bar-wrap">';
      html += '<div class="completion-bar-label" title="' + esc(item.label) + '">' + fileLink(item.label) + '</div>';
      html += '<div class="completion-bar-outer"><div class="completion-bar-inner" style="width:' + bPct + '%;background:#495057"></div></div>';
      html += '<div class="completion-bar-pct">' + item.value + '</div>';
      html += '</div>';
    }
  }

  container.innerHTML = html;
  state.dirty.stats = false;
}
