// ===== Panel: Preview =====
function renderPreview(container) {
  var html = '<div class="preview-controls">';

  // Mode selector
  html += '<div class="ctrl-group"><label>Mode</label>';
  html += '<select id="previewMode">';
  html += '<option value="hook-read-standard"' + (state.previewMode === 'hook-read-standard' ? ' selected' : '') + '>Hook: Read (standard)</option>';
  html += '<option value="hook-read-narrative"' + (state.previewMode === 'hook-read-narrative' ? ' selected' : '') + '>Hook: Read (narrative)</option>';
  html += '<option value="mcp-bdd_motivation"' + (state.previewMode === 'mcp-bdd_motivation' ? ' selected' : '') + '>MCP: bdd_motivation</option>';
  html += '<option value="mcp-bdd_tree"' + (state.previewMode === 'mcp-bdd_tree' ? ' selected' : '') + '>MCP: bdd_tree</option>';
  html += '<option value="mcp-bdd_status"' + (state.previewMode === 'mcp-bdd_status' ? ' selected' : '') + '>MCP: bdd_status</option>';
  html += '<option value="mcp-bdd_locate"' + (state.previewMode === 'mcp-bdd_locate' ? ' selected' : '') + '>MCP: bdd_locate</option>';
  html += '<option value="mcp-bdd_next"' + (state.previewMode === 'mcp-bdd_next' ? ' selected' : '') + '>MCP: bdd_next</option>';
  html += '</select></div>';

  // File path input with autocomplete
  html += '<div class="ctrl-group"><label>File path</label>';
  html += '<div class="autocomplete-wrap"><input type="text" id="previewFile" placeholder="e.g. backend/project_manager.py" style="width:260px" />';
  html += '<div class="autocomplete-list" id="previewFileAC"></div></div></div>';

  // Node ID input
  html += '<div class="ctrl-group"><label>Node ID</label>';
  html += '<input type="text" id="previewNodeId" placeholder="e.g. g-001, e-005" style="width:100px" /></div>';

  // Start/end line
  html += '<div class="ctrl-group"><label>Start line</label>';
  html += '<input type="number" id="previewStartLine" placeholder="0" style="width:60px" /></div>';
  html += '<div class="ctrl-group"><label>End line</label>';
  html += '<input type="number" id="previewEndLine" placeholder="0" style="width:60px" /></div>';

  // Status filter
  html += '<div class="ctrl-group"><label>Status filter</label>';
  html += '<input type="text" id="previewStatusFilter" placeholder="e.g. unsatisfied" style="width:100px" /></div>';

  // Max depth
  html += '<div class="ctrl-group"><label>Max depth</label>';
  html += '<input type="number" id="previewMaxDepth" placeholder="0" style="width:50px" /></div>';

  html += '<button class="btn-generate" id="btnGenerate">Generate</button>';
  html += '</div>';

  html += '<div class="preview-output" id="previewOutput">Select a mode and click Generate to see the LLM preview.</div>';

  container.innerHTML = html;

  // Mode change handler — show/hide relevant inputs
  var modeSelect = document.getElementById('previewMode');
  function updateInputVisibility() {
    var mode = modeSelect.value;
    state.previewMode = mode;
    var fileInput = document.getElementById('previewFile').parentNode.parentNode;
    var nodeInput = document.getElementById('previewNodeId').parentNode;
    var startLine = document.getElementById('previewStartLine').parentNode;
    var endLine = document.getElementById('previewEndLine').parentNode;
    var statusFilter = document.getElementById('previewStatusFilter').parentNode;
    var maxDepth = document.getElementById('previewMaxDepth').parentNode;

    fileInput.style.display = 'none';
    nodeInput.style.display = 'none';
    startLine.style.display = 'none';
    endLine.style.display = 'none';
    statusFilter.style.display = 'none';
    maxDepth.style.display = 'none';

    if (mode === 'hook-read-standard' || mode === 'hook-read-narrative') {
      fileInput.style.display = '';
    } else if (mode === 'mcp-bdd_motivation') {
      fileInput.style.display = '';
      startLine.style.display = '';
      endLine.style.display = '';
    } else if (mode === 'mcp-bdd_tree') {
      nodeInput.style.display = '';
      statusFilter.style.display = '';
      maxDepth.style.display = '';
    } else if (mode === 'mcp-bdd_locate') {
      nodeInput.style.display = '';
    }
    // bdd_status and bdd_next have no inputs
  }
  modeSelect.addEventListener('change', updateInputVisibility);
  updateInputVisibility();

  // Autocomplete for file path
  var fileInput = document.getElementById('previewFile');
  var acList = document.getElementById('previewFileAC');
  var acActiveIdx = -1;

  fileInput.addEventListener('input', function() {
    var val = this.value.toLowerCase();
    acList.innerHTML = '';
    acActiveIdx = -1;
    if (!val) { acList.classList.remove('show'); return; }
    var matches = [];
    for (var i = 0; i < knownFiles.length && matches.length < 15; i++) {
      if (knownFiles[i].toLowerCase().indexOf(val) >= 0) matches.push(knownFiles[i]);
    }
    if (matches.length === 0) { acList.classList.remove('show'); return; }
    for (var j = 0; j < matches.length; j++) {
      var div = document.createElement('div');
      div.className = 'autocomplete-item';
      div.textContent = matches[j];
      div.addEventListener('click', function() {
        fileInput.value = this.textContent;
        acList.classList.remove('show');
      });
      acList.appendChild(div);
    }
    acList.classList.add('show');
  });

  fileInput.addEventListener('keydown', function(e) {
    var items = acList.querySelectorAll('.autocomplete-item');
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      acActiveIdx = Math.min(acActiveIdx + 1, items.length - 1);
      for (var i = 0; i < items.length; i++) items[i].classList.toggle('active', i === acActiveIdx);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      acActiveIdx = Math.max(acActiveIdx - 1, 0);
      for (var i = 0; i < items.length; i++) items[i].classList.toggle('active', i === acActiveIdx);
    } else if (e.key === 'Enter' && acActiveIdx >= 0 && items[acActiveIdx]) {
      e.preventDefault();
      fileInput.value = items[acActiveIdx].textContent;
      acList.classList.remove('show');
    }
  });

  document.addEventListener('click', function(e) {
    if (!fileInput.contains(e.target) && !acList.contains(e.target)) {
      acList.classList.remove('show');
    }
  });

  // Generate button
  document.getElementById('btnGenerate').addEventListener('click', function() {
    var output = document.getElementById('previewOutput');
    var mode = document.getElementById('previewMode').value;
    var result = '';
    try {
      if (mode === 'hook-read-standard') {
        result = simulateHookStandard(document.getElementById('previewFile').value);
      } else if (mode === 'hook-read-narrative') {
        result = simulateHookNarrative(document.getElementById('previewFile').value);
      } else if (mode === 'mcp-bdd_motivation') {
        result = simulateBddMotivation(
          document.getElementById('previewFile').value,
          parseInt(document.getElementById('previewStartLine').value) || 0,
          parseInt(document.getElementById('previewEndLine').value) || 0
        );
      } else if (mode === 'mcp-bdd_tree') {
        result = simulateBddTree(
          document.getElementById('previewNodeId').value,
          document.getElementById('previewStatusFilter').value,
          parseInt(document.getElementById('previewMaxDepth').value) || 0
        );
      } else if (mode === 'mcp-bdd_status') {
        result = simulateBddStatus();
      } else if (mode === 'mcp-bdd_locate') {
        result = simulateBddLocate(document.getElementById('previewNodeId').value);
      } else if (mode === 'mcp-bdd_next') {
        result = simulateBddNext();
      }
    } catch(e) {
      result = 'Error: ' + e.message;
    }
    output.innerHTML = highlightBddOutput(result);
  });
}
