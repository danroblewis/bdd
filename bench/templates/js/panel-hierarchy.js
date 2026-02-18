// ===== Panel: Hierarchy =====
function renderHierarchy(container) {
  var goals = state.activeGoal ? [nodeMap[state.activeGoal]] : goalNodes;
  var html = '';

  // Render hierarchy controls
  var ctrlEl = document.getElementById('hierarchyControls');
  if (ctrlEl) {
    ctrlEl.innerHTML = '<div class="hierarchy-controls">' +
      '<button onclick="expandAllFacets()">Expand All</button>' +
      '<button onclick="collapseAllFacets()">Collapse All</button></div>';
  }

  for (var gi = 0; gi < goals.length; gi++) {
    var g = goals[gi];
    if (!g) continue;
    if (state.searchPattern && !subtreeMatchesSearch(g.id)) continue;

    var gStatus = computeStatus(g);
    var exps = getChildren(g.id);
    exps.sort(function(a, b) { return (a.priority || 99) - (b.priority || 99); });

    html += '<div class="card node-goal">';
    html += '<h3><span class="card-id id-goal">' + g.id + '</span>' + highlightText(g.text) + '</h3>';
    html += '<div class="meta-row">';
    if (g.priority) html += '<span class="chip chip-priority">P' + g.priority + '</span>';
    if (g.labels) {
      for (var li = 0; li < g.labels.length; li++) html += '<span class="chip">' + esc(g.labels[li]) + '</span>';
    }
    html += ' ' + statusBadge(gStatus);
    html += ' <span style="color:#6c757d;font-size:11px">' + exps.length + ' expectations</span>';
    html += '</div>';

    for (var ei = 0; ei < exps.length; ei++) {
      var e = exps[ei];
      if (state.searchPattern && !subtreeMatchesSearch(e.id)) continue;

      var eStatus = computeStatus(e);
      var facets = getChildren(e.id);

      // Count passing facets
      var passingCount = 0;
      var visibleFacetCount = 0;
      for (var ci = 0; ci < facets.length; ci++) {
        if (state.searchPattern && !nodeMatchesSearch(facets[ci])) continue;
        visibleFacetCount++;
        if ((facets[ci].status || 'untested') === 'passing') passingCount++;
      }

      // Auto-expand if search matches any facet in this group
      var autoExpand = false;
      if (state.searchPattern) {
        for (var si = 0; si < facets.length; si++) {
          if (nodeMatchesSearch(facets[si])) { autoExpand = true; break; }
        }
      }

      html += '<div class="exp-group">';
      html += '<div class="card node-exp">';
      html += '<h4><span class="card-id id-exp">' + e.id + '</span>' + highlightText(e.text) + '</h4>';
      html += '<div class="meta-row">';
      if (e.priority) html += '<span class="chip chip-priority">P' + e.priority + '</span>';
      if (e.labels) {
        for (var lj = 0; lj < e.labels.length; lj++) html += '<span class="chip">' + esc(e.labels[lj]) + '</span>';
      }
      html += ' ' + statusBadge(eStatus);
      html += ' <span style="color:#6c757d;font-size:11px">' + facets.length + ' facets</span>';
      html += '</div>';

      // Facet toggle row
      if (facets.length > 0) {
        var expanded = autoExpand;
        html += '<div class="facet-toggle" data-exp-id="' + e.id + '">';
        html += '<span class="toggle-arrow' + (expanded ? ' expanded' : '') + '">&#9654;</span>';
        html += '<span class="toggle-summary">' + visibleFacetCount + ' facets</span>';
        html += '<span class="toggle-status">' + passingCount + ' passing</span>';
        html += '</div>';

        // Facet group (collapsed by default unless search match)
        html += '<div class="facet-group' + (expanded ? '' : ' collapsed') + '" data-facet-group="' + e.id + '">';
        for (var fi = 0; fi < facets.length; fi++) {
          var f = facets[fi];
          if (state.searchPattern && !nodeMatchesSearch(f)) continue;

          var loc = derived.located_in[f.id];
          html += '<div class="card node-facet">';
          html += '<div class="meta-row"><span class="card-id id-facet">' + f.id + '</span>' + statusBadge(f.status || 'untested') + '</div>';
          html += '<div style="margin:4px 0;font-size:12px">' + highlightText(f.text) + '</div>';
          if (loc) {
            var locFile = loc.split(':')[0];
            html += '<div class="meta-row"><span class="label">Source:</span><span class="val">' + fileLinkHighlight(locFile) + '</span></div>';
          }
          if (f.test) {
            html += '<div class="meta-row"><span class="label">Test:</span><span class="val">' + highlightText(f.test) + '</span></div>';
          }
          html += '</div>';
        }
        html += '</div>';
      }

      html += '</div></div>';
    }
    html += '</div>';
  }
  if (!html) html = '<div style="color:#6c757d;padding:20px">No matching nodes found.</div>';
  container.innerHTML = html;
  state.dirty.hierarchy = false;
}

// Facet toggle click handler (event delegation)
function setupFacetToggle() {
  document.getElementById('hierarchyContent').addEventListener('click', function(e) {
    var toggle = e.target.closest('.facet-toggle');
    if (!toggle) return;
    var expId = toggle.getAttribute('data-exp-id');
    var group = document.querySelector('[data-facet-group="' + expId + '"]');
    var arrow = toggle.querySelector('.toggle-arrow');
    if (group) {
      group.classList.toggle('collapsed');
      if (arrow) arrow.classList.toggle('expanded');
    }
  });
}

function expandAllFacets() {
  var groups = document.querySelectorAll('.facet-group.collapsed');
  for (var i = 0; i < groups.length; i++) groups[i].classList.remove('collapsed');
  var arrows = document.querySelectorAll('.toggle-arrow');
  for (var j = 0; j < arrows.length; j++) arrows[j].classList.add('expanded');
}

function collapseAllFacets() {
  var groups = document.querySelectorAll('.facet-group');
  for (var i = 0; i < groups.length; i++) groups[i].classList.add('collapsed');
  var arrows = document.querySelectorAll('.toggle-arrow');
  for (var j = 0; j < arrows.length; j++) arrows[j].classList.remove('expanded');
}
