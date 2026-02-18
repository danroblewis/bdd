// ===== Init =====
renderTopCounts();
renderSidebar();
setupSearch();
renderPreview(document.getElementById('previewContent'));
setupFacetToggle();
renderAll();

// View tab switching
var viewTabs = document.querySelectorAll('.view-tab');
for (var vt = 0; vt < viewTabs.length; vt++) {
  viewTabs[vt].addEventListener('click', function() {
    switchView(this.getAttribute('data-view'));
  });
}

// Global click handler for file links
document.addEventListener('click', function(e) {
  var link = e.target.closest('.file-link');
  if (!link) return;
  e.preventDefault();
  var filePath = link.getAttribute('data-file');
  if (filePath) {
    state.fileDetailPath = filePath;
    state.dirty.files = true;
    // Switch to catalog view if on preview
    if (state.activeView !== 'catalog') switchView('catalog');
    renderAll();
  }
});
