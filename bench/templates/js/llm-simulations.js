// ===== LLM Simulation functions =====

function findFacetsForFile(filePath) {
  if (!filePath) return [];
  var facetIds = [];
  for (var f in forwardMap) {
    if (f.indexOf(filePath) >= 0 || filePath.indexOf(f) >= 0) {
      var fids = forwardMap[f];
      for (var i = 0; i < fids.length; i++) facetIds.push(fids[i]);
    }
  }
  return facetIds;
}

function buildDeduplicatedTree(facetIds) {
  var treeNodes = {};
  var treeRoots = {};
  for (var fi = 0; fi < facetIds.length; fi++) {
    var fid = facetIds[fi];
    var chain = getAncestorChain(fid);
    for (var i = 0; i < chain.length; i++) {
      var n = chain[i];
      if (!treeNodes[n.id]) {
        treeNodes[n.id] = {node: n, children: {}};
      }
      if (i > 0) {
        treeNodes[chain[i - 1].id].children[n.id] = true;
      } else {
        treeRoots[n.id] = true;
      }
    }
  }
  return {treeNodes: treeNodes, treeRoots: treeRoots};
}

function simulateHookStandard(filePath) {
  var facetIds = findFacetsForFile(filePath);
  if (facetIds.length === 0) return 'No catalog entries related to ' + filePath;

  var tree = buildDeduplicatedTree(facetIds);
  var lines = ['--- BDD: This code exists because ---'];

  function render(nid, indent) {
    var tn = tree.treeNodes[nid];
    if (!tn) return;
    var n = tn.node;
    var prefix = '';
    for (var p = 0; p < indent; p++) prefix += '  ';
    var t = n.type.charAt(0).toUpperCase();
    lines.push('  ' + prefix + n.id + ' [' + t + '] ' + n.text);
    var childIds = Object.keys(tn.children).sort();
    for (var i = 0; i < childIds.length; i++) {
      render(childIds[i], indent + 1);
    }
  }

  var rootIds = Object.keys(tree.treeRoots).sort();
  for (var ri = 0; ri < rootIds.length; ri++) {
    render(rootIds[ri], 0);
  }
  lines.push('---');
  return lines.join('\n');
}

function simulateHookNarrative(filePath) {
  var facetIds = findFacetsForFile(filePath);
  if (facetIds.length === 0) return 'No catalog entries related to ' + filePath;

  // Build goal -> expectation -> facets structure
  var structure = {};
  for (var fi = 0; fi < facetIds.length; fi++) {
    var fid = facetIds[fi];
    var facet = nodeMap[fid];
    if (!facet) continue;

    var expNode = null, goalNode = null;
    var current = nodeMap[facet.parent];
    while (current) {
      if (current.type === 'expectation' && !expNode) expNode = current;
      else if (current.type === 'goal') { goalNode = current; break; }
      current = current.parent ? nodeMap[current.parent] : null;
    }
    if (!goalNode || !expNode) continue;

    var gid = goalNode.id, eid = expNode.id;
    if (!structure[gid]) structure[gid] = {node: goalNode, expectations: {}};
    if (!structure[gid].expectations[eid]) structure[gid].expectations[eid] = {node: expNode, facets: []};
    structure[gid].expectations[eid].facets.push(facet);
  }

  if (Object.keys(structure).length === 0) return 'No catalog entries related to ' + filePath;

  // Render prose
  var basename = filePath.split('/').pop();
  var moduleName = basename.replace(/\.[^.]+$/, '');
  var linesOut = ['--- Why this code exists ---'];

  var gids = Object.keys(structure).sort();
  for (var gi = 0; gi < gids.length; gi++) {
    var gdata = structure[gids[gi]];
    var goalText = gdata.node.text;
    var expCount = Object.keys(gdata.expectations).length;

    linesOut.push('This module is part of the ' + moduleName + ' layer. It was designed to ' + goalText.toLowerCase() + ' (' + gids[gi] + ').');
    linesOut.push('');

    if (expCount === 1) {
      var eid = Object.keys(gdata.expectations)[0];
      var edata = gdata.expectations[eid];
      var expText = edata.node.text;
      linesOut.push('The code you\'re reading implements: **' + expText + '** (' + eid + ').');
      for (var fj = 0; fj < edata.facets.length; fj++) {
        linesOut.push('- ' + edata.facets[fj].text);
      }
    } else {
      linesOut.push('The code you\'re reading implements multiple user expectations:');
      var eids = Object.keys(gdata.expectations).sort();
      for (var ek = 0; ek < eids.length; ek++) {
        var ed = gdata.expectations[eids[ek]];
        var facetSummaries = [];
        for (var fl = 0; fl < ed.facets.length; fl++) {
          var ft = ed.facets[fl].text;
          var funcPart;
          if (ft.indexOf(':') >= 0) {
            var before = ft.substring(0, ft.indexOf(':'));
            funcPart = before.indexOf('.') >= 0 ? before : (ft.indexOf(' ') >= 0 ? ft.substring(0, ft.indexOf(' ')) : ft);
          } else {
            funcPart = ft.substring(0, 40);
          }
          facetSummaries.push(funcPart);
        }
        linesOut.push('- **' + ed.node.text + '** (' + eids[ek] + '): ' + facetSummaries.join(', '));
      }
    }
  }
  linesOut.push('---');
  return linesOut.join('\n');
}

function simulateBddMotivation(filePath, startLine, endLine) {
  var facetIds = findFacetsForFile(filePath);
  if (facetIds.length === 0) {
    return 'No catalog entries related to ' + filePath + (startLine ? ' lines ' + startLine + '-' + endLine : '');
  }

  var tree = buildDeduplicatedTree(facetIds);
  var lines = ['--- This code exists because ---'];

  function render(nid, indent) {
    var tn = tree.treeNodes[nid];
    if (!tn) return;
    var n = tn.node;
    var prefix = '';
    for (var p = 0; p < indent; p++) prefix += '  ';
    var t = n.type.charAt(0).toUpperCase();
    lines.push('  ' + prefix + n.id + ' [' + t + '] ' + n.text);
    var childIds = Object.keys(tn.children).sort();
    for (var i = 0; i < childIds.length; i++) {
      render(childIds[i], indent + 1);
    }
  }

  var rootIds = Object.keys(tree.treeRoots).sort();
  for (var ri = 0; ri < rootIds.length; ri++) {
    render(rootIds[ri], 0);
  }
  lines.push('---');
  return lines.join('\n');
}

function simulateBddTree(nodeId, statusFilter, maxDepth) {
  var roots;
  if (nodeId) {
    var target = nodeMap[nodeId];
    if (!target) return "Node '" + nodeId + "' not found";
    roots = [target];
  } else {
    roots = [];
    for (var i = 0; i < nodes.length; i++) {
      if (!nodes[i].parent) roots.push(nodes[i]);
    }
  }
  roots.sort(function(a, b) { return (a.priority || 99) - (b.priority || 99); });

  var lines = [];

  function shouldShow(node) {
    if (!statusFilter) return true;
    var s = computeStatus(node);
    if (statusFilter === 'unsatisfied') return s !== 'passing';
    if (statusFilter === 'failing') return s === 'failing';
    if (statusFilter === 'untested') return s === 'untested';
    if (statusFilter === 'passing') return s === 'passing';
    return true;
  }

  function printTree(node, indent, depth) {
    if (maxDepth && depth > maxDepth) return;
    var status = computeStatus(node);
    var icon = statusIcon(status);
    var prefix = '';
    for (var p = 0; p < indent; p++) prefix += '  ';
    var typeLabel = node.type.charAt(0).toUpperCase();
    lines.push(prefix + icon + ' ' + node.id + ' [' + typeLabel + '] ' + node.text);
    var children = getChildren(node.id);
    children.sort(function(a, b) { return (a.priority || 99) - (b.priority || 99); });
    for (var i = 0; i < children.length; i++) {
      if (shouldShow(children[i])) {
        printTree(children[i], indent + 1, depth + 1);
      }
    }
  }

  if (roots.length === 0) return 'Catalog is empty.';
  for (var ri = 0; ri < roots.length; ri++) {
    if (shouldShow(roots[ri])) {
      printTree(roots[ri], 0, 1);
    }
  }

  if (lines.length === 0) return "No nodes match filter (status_filter='" + statusFilter + "')";
  return lines.join('\n');
}

function simulateBddStatus() {
  var passing = [], failing = [], untested = [];
  for (var i = 0; i < facetNodes.length; i++) {
    var s = facetNodes[i].status || 'untested';
    if (s === 'passing') passing.push(facetNodes[i]);
    else if (s === 'failing') failing.push(facetNodes[i]);
    else untested.push(facetNodes[i]);
  }
  var total = facetNodes.length;
  var coverage = total > 0 ? (passing.length / total * 100) : 0;

  var satisfied = 0;
  var unsatisfiedExps = [];
  for (var j = 0; j < expNodes.length; j++) {
    if (computeStatus(expNodes[j]) === 'passing') satisfied++;
    else unsatisfiedExps.push(expNodes[j]);
  }
  unsatisfiedExps.sort(function(a, b) { return (a.priority || 99) - (b.priority || 99); });

  var lines = [
    'Goals: ' + goalNodes.length + '  Expectations: ' + expNodes.length + '  Facets: ' + total,
    'Passing: ' + passing.length + '  Failing: ' + failing.length + '  Untested: ' + untested.length,
    'Coverage: ' + Math.round(coverage * 10) / 10 + '%  Satisfied: ' + satisfied + '/' + expNodes.length
  ];

  if (unsatisfiedExps.length > 0) {
    lines.push('');
    lines.push('Top unsatisfied (' + unsatisfiedExps.length + ' total):');
    var showCount = Math.min(unsatisfiedExps.length, 10);
    for (var k = 0; k < showCount; k++) {
      var exp = unsatisfiedExps[k];
      var parent = exp.parent ? nodeMap[exp.parent] : null;
      var prefix = parent ? parent.id : '?';
      var status = computeStatus(exp);
      lines.push('  ' + exp.id + ' [' + status + '] ' + exp.text + '  (' + prefix + ')');
      var facets = getChildren(exp.id);
      for (var f = 0; f < facets.length; f++) {
        var fs = facets[f].status || 'untested';
        if (fs !== 'passing') {
          lines.push('    ' + facets[f].id + ' [' + fs + '] ' + facets[f].text);
        }
      }
    }
  }
  return lines.join('\n');
}

function simulateBddLocate(nodeId) {
  if (!nodeId) return 'Please provide a node ID';
  var node = nodeMap[nodeId];
  if (!node) return "Node '" + nodeId + "' not found";

  // Collect target facet IDs
  var targetIds = [];
  if (node.type === 'facet') {
    targetIds = [nodeId];
  } else {
    function collectFacets(nid) {
      var n = nodeMap[nid];
      if (!n) return;
      if (n.type === 'facet') targetIds.push(nid);
      var kids = childrenMap[nid] || [];
      for (var i = 0; i < kids.length; i++) collectFacets(kids[i]);
    }
    collectFacets(nodeId);
  }

  if (targetIds.length === 0) return 'No facets found under ' + nodeId;

  // Gather files from Located in
  var fileInfo = {};
  for (var i = 0; i < targetIds.length; i++) {
    var loc = derived.located_in[targetIds[i]];
    if (loc) {
      var filePart = loc.split(':')[0];
      if (!fileInfo[filePart]) fileInfo[filePart] = [];
      fileInfo[filePart].push(targetIds[i]);
    }
    // Also check test field
    var tn = nodeMap[targetIds[i]];
    if (tn && tn.test) {
      var testFile = tn.test.split('::')[0];
      if (!fileInfo[testFile]) fileInfo[testFile] = [];
      fileInfo[testFile].push(targetIds[i] + ' (test)');
    }
  }

  if (Object.keys(fileInfo).length === 0) {
    return 'No coverage data for ' + nodeId + '. Run bdd_test first to build the index.';
  }

  var resultLines = ['Implementation of ' + nodeId + ' (' + node.text + '):'];
  var sortedFiles = Object.keys(fileInfo).sort();
  for (var fi = 0; fi < sortedFiles.length; fi++) {
    var f = sortedFiles[fi];
    resultLines.push('  ' + f + ': facets ' + fileInfo[f].join(', '));
  }
  return resultLines.join('\n');
}

function simulateBddNext() {
  var unsatisfied = [];
  for (var i = 0; i < expNodes.length; i++) {
    if (computeStatus(expNodes[i]) !== 'passing') unsatisfied.push(expNodes[i]);
  }
  unsatisfied.sort(function(a, b) { return (a.priority || 99) - (b.priority || 99); });

  if (unsatisfied.length === 0) return JSON.stringify({all_satisfied: true, message: 'All expectations satisfied!'});

  var exp = unsatisfied[0];
  var facets = getChildren(exp.id);
  var parent = exp.parent ? nodeMap[exp.parent] : null;

  var lines = [];
  if (parent) {
    lines.push('Goal: ' + parent.id + ' \u2014 ' + parent.text);
    lines.push('');
  }
  lines.push('Expectation: ' + exp.id + ' \u2014 ' + exp.text);
  if (exp.priority) lines.push('Priority: ' + exp.priority);
  lines.push('');
  if (facets.length > 0) {
    lines.push('Facets:');
    for (var j = 0; j < facets.length; j++) {
      var f = facets[j];
      var icon = statusIcon(f.status || 'untested');
      var test = f.test ? ' (test: ' + f.test + ')' : '';
      lines.push('  ' + icon + ' ' + f.id + ' \u2014 ' + f.text + test);
    }
  } else {
    lines.push('No facets yet \u2014 decompose this expectation into testable facets.');
  }
  return lines.join('\n');
}
