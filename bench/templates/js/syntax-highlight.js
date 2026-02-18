// ===== Syntax Highlighting for BDD output =====
function highlightBddOutput(text) {
  if (!text) return '';
  // Escape HTML first
  var s = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');

  // Section delimiters: --- BDD: ... ---, --- Why ... ---, --- This ... ---
  s = s.replace(/(---\s*(?:BDD:|Why|This).*?---)/g, '<span class="hl-delimiter">$1</span>');
  // Bare closing delimiter ---
  s = s.replace(/^(---)$/gm, '<span class="hl-delimiter">$1</span>');

  // Status icons [+] [-] [ ]
  s = s.replace(/\[\+\]/g, '<span class="hl-status-pass">[+]</span>');
  s = s.replace(/\[-\]/g, '<span class="hl-status-fail">[-]</span>');
  s = s.replace(/\[ \]/g, '<span class="hl-status-untested">[ ]</span>');

  // Type markers [G] [E] [F]
  s = s.replace(/\[G\]/g, '<span class="hl-type-g">[G]</span>');
  s = s.replace(/\[E\]/g, '<span class="hl-type-e">[E]</span>');
  s = s.replace(/\[F\]/g, '<span class="hl-type-f">[F]</span>');

  // Goal IDs g-001
  s = s.replace(/\b(g-\d{3})\b/g, '<span class="hl-goal-id">$1</span>');

  // Expectation IDs e-001
  s = s.replace(/\b(e-\d{3})\b/g, '<span class="hl-exp-id">$1</span>');

  // Facet IDs f-001
  s = s.replace(/\b(f-\d{3})\b/g, '<span class="hl-facet-id">$1</span>');

  // File paths (word/word.ext pattern)
  s = s.replace(/([\w][\w\/\-]*\/[\w\/\-]+\.\w+)/g, '<span class="hl-filepath">$1</span>');

  // Keywords at start of line: Goal:, Expectation:, Facets:, Priority:, etc.
  s = s.replace(/^(\s*)(Goal|Expectation|Facets|Priority|Passing|Failing|Untested|Coverage|Satisfied|Implementation|Goals|Expectations|Top unsatisfied)(:)/gm,
    '$1<span class="hl-keyword">$2</span>$3');

  // Status words in brackets [passing] [failing] [untested] [unsatisfied]
  s = s.replace(/\[(passing)\]/g, '<span class="hl-status-pass">[$1]</span>');
  s = s.replace(/\[(failing)\]/g, '<span class="hl-status-fail">[$1]</span>');
  s = s.replace(/\[(untested)\]/g, '<span class="hl-status-untested">[$1]</span>');

  return s;
}
