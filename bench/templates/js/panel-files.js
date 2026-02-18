// ===== Panel: Files =====
function renderFiles(container) {
  var html = '';

  // Filter files if a goal is selected
  var visibleFacets = {};
  if (state.activeGoal) {
    var gNode = nodeMap[state.activeGoal];
    if (gNode) {
      function collectFacetIds(nid) {
        var n = nodeMap[nid];
        if (!n) return;
        if (n.type === 'facet') visibleFacets[nid] = true;
        var kids = childrenMap[nid] || [];
        for (var i = 0; i < kids.length; i++) collectFacetIds(kids[i]);
      }
      collectFacetIds(state.activeGoal);
    }
  }

  function filterFileMap(fmap) {
    if (!state.activeGoal) return fmap;
    var filtered = {};
    for (var file in fmap) {
      var fids = fmap[file];
      var kept = [];
      for (var i = 0; i < fids.length; i++) {
        if (visibleFacets[fids[i]]) kept.push(fids[i]);
      }
      if (kept.length > 0) filtered[file] = kept;
    }
    return filtered;
  }

  function matchesFileSearch(file, fids) {
    if (!state.searchPattern) return true;
    if (state.searchPattern.test(file)) return true;
    for (var i = 0; i < fids.length; i++) {
      if (state.searchPattern.test(fids[i])) return true;
    }
    return false;
  }

  // Source files
  var srcMap = filterFileMap(derived.file_map);
  html += '<h3 style="margin-bottom:8px">Source Files</h3>';
  var dirs = {};
  for (var sf in srcMap) {
    if (!matchesFileSearch(sf, srcMap[sf])) continue;
    var parts = sf.split('/');
    var dir = parts.length > 1 ? parts.slice(0, -1).join('/') : '.';
    if (!dirs[dir]) dirs[dir] = [];
    dirs[dir].push({file: sf, fids: srcMap[sf]});
  }
  var sortedDirs = Object.keys(dirs).sort();
  if (sortedDirs.length === 0) {
    html += '<div style="color:#6c757d;margin-bottom:16px">No source files found.</div>';
  } else {
    for (var di = 0; di < sortedDirs.length; di++) {
      var d = sortedDirs[di];
      html += '<div class="file-tree">';
      html += '<div class="file-dir">' + esc(d) + '/</div>';
      var entries = dirs[d].sort(function(a, b) { return a.file < b.file ? -1 : 1; });
      for (var ei = 0; ei < entries.length; ei++) {
        var entry = entries[ei];
        html += '<div class="file-entry">' + fileLinkHighlight(entry.file);
        html += ' <span class="fids">' + entry.fids.join(', ') + '</span></div>';
      }
      html += '</div>';
    }
  }

  // Test files
  var tstMap = filterFileMap(derived.test_map);
  html += '<h3 style="margin:16px 0 8px">Test Files</h3>';
  var tdirs = {};
  for (var tf in tstMap) {
    if (!matchesFileSearch(tf, tstMap[tf])) continue;
    var tparts = tf.split('/');
    var tdir = tparts.length > 1 ? tparts.slice(0, -1).join('/') : '.';
    if (!tdirs[tdir]) tdirs[tdir] = [];
    tdirs[tdir].push({file: tf, fids: tstMap[tf]});
  }
  var tsortedDirs = Object.keys(tdirs).sort();
  if (tsortedDirs.length === 0) {
    html += '<div style="color:#6c757d;margin-bottom:16px">No test files found.</div>';
  } else {
    for (var tdi = 0; tdi < tsortedDirs.length; tdi++) {
      var td = tsortedDirs[tdi];
      html += '<div class="file-tree">';
      html += '<div class="file-dir">' + esc(td) + '/</div>';
      var tentries = tdirs[td].sort(function(a, b) { return a.file < b.file ? -1 : 1; });
      for (var tei = 0; tei < tentries.length; tei++) {
        var tentry = tentries[tei];
        html += '<div class="file-entry">' + fileLinkHighlight(tentry.file);
        html += ' <span class="fids">' + tentry.fids.join(', ') + '</span></div>';
      }
      html += '</div>';
    }
  }

  container.innerHTML = html;
  state.dirty.files = false;
}

// ===== File Detail View (reverse-tree) =====
function renderFileDetail(filePath, container) {
  var html = '';
  html += '<div class="file-detail-back" onclick="clearFileDetail()">&#8592; Back to file list</div>';
  html += '<div class="file-detail-title">' + esc(filePath) + '</div>';

  // Find all facets referencing this file
  var facetIds = [];
  for (var fid in derived.located_in) {
    var loc = derived.located_in[fid];
    var locFile = loc.split(':')[0];
    if (locFile === filePath) facetIds.push(fid);
  }

  html += '<div class="file-detail-count">' + facetIds.length + ' facets reference this file</div>';

  if (facetIds.length === 0) {
    html += '<div style="color:#6c757d">No facets found for this file.</div>';
    container.innerHTML = html;
    state.dirty.files = false;
    return;
  }

  // Build reverse tree: group facets by goal -> expectation
  var goalGroups = {};
  for (var i = 0; i < facetIds.length; i++) {
    var facet = nodeMap[facetIds[i]];
    if (!facet) continue;

    // Walk up to find expectation and goal
    var expNode = null, goalNode = null;
    var current = nodeMap[facet.parent];
    while (current) {
      if (current.type === 'expectation' && !expNode) expNode = current;
      else if (current.type === 'goal') { goalNode = current; break; }
      current = current.parent ? nodeMap[current.parent] : null;
    }
    if (!goalNode || !expNode) continue;

    var gid = goalNode.id, eid = expNode.id;
    if (!goalGroups[gid]) goalGroups[gid] = {node: goalNode, expectations: {}};
    if (!goalGroups[gid].expectations[eid]) goalGroups[gid].expectations[eid] = {node: expNode, facets: []};
    goalGroups[gid].expectations[eid].facets.push(facet);
  }

  // Render reverse tree
  var gids = Object.keys(goalGroups).sort();
  for (var gi = 0; gi < gids.length; gi++) {
    var gdata = goalGroups[gids[gi]];
    var g = gdata.node;
    html += '<div class="card node-goal" style="margin-top:8px">';
    html += '<h3><span class="card-id id-goal">[G]</span> <span class="card-id id-goal">' + g.id + '</span>' + esc(g.text) + '</h3>';

    var eids = Object.keys(gdata.expectations).sort();
    for (var ej = 0; ej < eids.length; ej++) {
      var edata = gdata.expectations[eids[ej]];
      var exp = edata.node;
      html += '<div class="exp-group">';
      html += '<div class="card node-exp">';
      html += '<h4><span class="card-id id-exp">[E]</span> <span class="card-id id-exp">' + exp.id + '</span>' + esc(exp.text) + '</h4>';

      html += '<div class="facet-group">';
      for (var fk = 0; fk < edata.facets.length; fk++) {
        var f = edata.facets[fk];
        html += '<div class="card node-facet">';
        html += '<div class="meta-row"><span class="card-id id-facet">[F]</span> <span class="card-id id-facet">' + f.id + '</span>' + statusBadge(f.status || 'untested') + '</div>';
        html += '<div style="margin:4px 0;font-size:12px">' + esc(f.text) + '</div>';
        html += '</div>';
      }
      html += '</div>';

      html += '</div></div>';
    }
    html += '</div>';
  }

  container.innerHTML = html;
  state.dirty.files = false;
}

function clearFileDetail() {
  state.fileDetailPath = null;
  state.dirty.files = true;
  renderAll();
}
