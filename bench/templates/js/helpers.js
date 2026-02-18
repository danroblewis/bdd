// ===== Helpers =====
function esc(s) {
  if (!s) return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function getChildren(parentId) {
  var ids = childrenMap[parentId] || [];
  var result = [];
  for (var i = 0; i < ids.length; i++) {
    if (nodeMap[ids[i]]) result.push(nodeMap[ids[i]]);
  }
  return result;
}

function getAncestorChain(nodeId) {
  var chain = [];
  var current = nodeMap[nodeId];
  while (current) {
    chain.push(current);
    current = current.parent ? nodeMap[current.parent] : null;
  }
  chain.reverse();
  return chain;
}

function computeStatus(node) {
  if (node.type === 'facet') return node.status || 'untested';
  var kids = getChildren(node.id);
  if (kids.length === 0) return 'untested';
  var allPassing = true, anyFailing = false;
  for (var i = 0; i < kids.length; i++) {
    var s = computeStatus(kids[i]);
    if (s !== 'passing') allPassing = false;
    if (s === 'failing') anyFailing = true;
  }
  if (allPassing) return 'passing';
  if (anyFailing) return 'failing';
  return 'untested';
}

function statusIcon(s) {
  if (s === 'passing') return '[+]';
  if (s === 'failing') return '[-]';
  return '[ ]';
}

function statusBadge(s) {
  return '<span class="status-' + s + '">' + s + '</span>';
}

function highlightText(text) {
  if (!state.searchPattern || !text) return esc(text);
  var escaped = esc(text);
  try {
    return escaped.replace(state.searchPattern, function(m) { return '<mark>' + m + '</mark>'; });
  } catch(e) { return escaped; }
}

function fileLink(filePath) {
  if (!filePath) return '';
  return '<span class="file-link" data-file="' + esc(filePath) + '">' + esc(filePath) + '</span>';
}

function fileLinkHighlight(filePath) {
  if (!filePath) return '';
  return '<span class="file-link" data-file="' + esc(filePath) + '">' + highlightText(filePath) + '</span>';
}

function nodeMatchesSearch(node) {
  if (!state.searchPattern) return true;
  var searchable = node.id + ' ' + (node.text || '') + ' ' + (node.test || '') +
    ' ' + ((node.labels || []).join(' '));
  var loc = derived.located_in[node.id];
  if (loc) searchable += ' ' + loc;
  return state.searchPattern.test(searchable);
}

function subtreeMatchesSearch(nodeId) {
  var node = nodeMap[nodeId];
  if (!node) return false;
  if (nodeMatchesSearch(node)) return true;
  var kids = childrenMap[nodeId] || [];
  for (var i = 0; i < kids.length; i++) {
    if (subtreeMatchesSearch(kids[i])) return true;
  }
  return false;
}

function countMatchesUnderGoal(goalId) {
  if (!state.searchPattern) return -1;
  var count = 0;
  function walk(nid) {
    var n = nodeMap[nid];
    if (n && nodeMatchesSearch(n)) count++;
    var kids = childrenMap[nid] || [];
    for (var i = 0; i < kids.length; i++) walk(kids[i]);
  }
  walk(goalId);
  return count;
}
