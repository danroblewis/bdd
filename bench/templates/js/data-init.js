// ===== Data setup =====
var catalog = DATA.catalog;
var derived = DATA.derived;
var nodes = catalog.nodes;
var nodeMap = {};
var childrenMap = {};
var goalNodes = [];
var expNodes = [];
var facetNodes = [];

// Build forward map from Located in: {file -> [facet_ids]}
var forwardMap = {};

(function dataInit() {
  var i, n;
  for (i = 0; i < nodes.length; i++) {
    n = nodes[i];
    nodeMap[n.id] = n;
    if (!childrenMap[n.id]) childrenMap[n.id] = [];
    if (n.parent) {
      if (!childrenMap[n.parent]) childrenMap[n.parent] = [];
      childrenMap[n.parent].push(n.id);
    }
  }
  for (i = 0; i < nodes.length; i++) {
    n = nodes[i];
    if (n.type === 'goal') goalNodes.push(n);
    else if (n.type === 'expectation') expNodes.push(n);
    else if (n.type === 'facet') facetNodes.push(n);
  }
  goalNodes.sort(function(a, b) { return (a.priority || 99) - (b.priority || 99); });

  // Build forwardMap
  for (var fid in derived.located_in) {
    var ref = derived.located_in[fid];
    var filePart = ref.split(':')[0];
    if (!forwardMap[filePart]) forwardMap[filePart] = [];
    forwardMap[filePart].push(fid);
  }
})();

var knownFiles = Object.keys(forwardMap).sort();
