/**
 * Pattern Tester component.
 * 
 * Allows users to test patterns against URLs and see if they match.
 * Used in both the approval dialog and the allowlist management UI.
 */

import { useState, useMemo, useEffect } from 'react';
import { Check, X, HelpCircle } from 'lucide-react';
import type { PatternType } from '../../utils/types';

interface PatternTesterProps {
  pattern: string;
  patternType: PatternType;
  testUrls?: string[];  // Initial URLs to test
  showHelp?: boolean;
}

// Convert wildcard pattern to regex for testing
function wildcardToRegex(pattern: string): RegExp {
  let regex = pattern
    .replace(/[.+?^${}()|[\]\\]/g, '\\$&')  // Escape special chars except *
    .replace(/\*/g, '.*');  // Convert * to .*
  return new RegExp(`^${regex}$`, 'i');
}

// Test if a URL matches a pattern
function testPattern(url: string, pattern: string, patternType: PatternType): boolean {
  try {
    const normalizedUrl = url.toLowerCase();
    const normalizedPattern = pattern.toLowerCase();
    
    switch (patternType) {
      case 'exact':
        // Exact match or prefix match
        return normalizedUrl === normalizedPattern || 
               normalizedUrl.startsWith(normalizedPattern + '/');
      
      case 'wildcard':
        const regex = wildcardToRegex(normalizedPattern);
        // Test against full URL and host
        try {
          const parsed = new URL(url.startsWith('http') ? url : `https://${url}`);
          return regex.test(normalizedUrl) || 
                 regex.test(parsed.host) ||
                 regex.test(parsed.host + parsed.pathname);
        } catch {
          return regex.test(normalizedUrl);
        }
      
      case 'regex':
        return new RegExp(pattern, 'i').test(url);
      
      default:
        return false;
    }
  } catch {
    return false;
  }
}

// Pattern syntax help
const PATTERN_HELP: Record<PatternType, string[]> = {
  exact: [
    'Matches the exact domain or URL',
    'Example: "api.example.com" matches only "api.example.com"',
  ],
  wildcard: [
    '* matches any characters',
    '*.example.com matches all subdomains',
    'api.example.com/* matches all paths',
    '*.example.com/* matches everything',
  ],
  regex: [
    'Full JavaScript regex syntax',
    '.*\\.example\\.com matches all subdomains',
    'api\\.example\\.com/v[12]/.*',
    'Use with caution - test thoroughly!',
  ],
};

export function PatternTester({ 
  pattern, 
  patternType, 
  testUrls = [],
  showHelp = true,
}: PatternTesterProps) {
  const [urls, setUrls] = useState<string[]>(testUrls);
  const [newUrl, setNewUrl] = useState('');
  
  // Update test URLs when initial urls change
  useEffect(() => {
    if (testUrls.length > 0) {
      setUrls(prev => {
        const combined = [...new Set([...testUrls, ...prev])];
        return combined;
      });
    }
  }, [testUrls]);
  
  // Test results
  const results = useMemo(() => {
    return urls.map(url => ({
      url,
      matches: testPattern(url, pattern, patternType),
    }));
  }, [urls, pattern, patternType]);
  
  const handleAddUrl = () => {
    if (newUrl.trim() && !urls.includes(newUrl.trim())) {
      setUrls([...urls, newUrl.trim()]);
      setNewUrl('');
    }
  };
  
  return (
    <div className="space-y-3">
      {/* Pattern syntax help */}
      {showHelp && (
        <div className="bg-[#0a0a0f] rounded border border-gray-700 p-2 text-xs">
          <div className="flex items-center gap-1 text-gray-400 mb-1">
            <HelpCircle size={12} />
            <span>{patternType === 'regex' ? 'Regex' : patternType === 'wildcard' ? 'Wildcard' : 'Exact'} pattern syntax:</span>
          </div>
          <ul className="text-gray-500 space-y-0.5 pl-4">
            {PATTERN_HELP[patternType].map((help, i) => (
              <li key={i}>• {help}</li>
            ))}
          </ul>
        </div>
      )}
      
      {/* Test URLs */}
      <div>
        <label className="text-xs text-gray-400 block mb-1">Test URLs:</label>
        
        {/* URL input */}
        <div className="flex gap-1 mb-2">
          <input
            type="text"
            value={newUrl}
            onChange={(e) => setNewUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAddUrl()}
            placeholder="Add URL to test..."
            className="flex-1 px-2 py-1 bg-[#1a1a24] border border-gray-600 rounded text-xs font-mono"
          />
          <button
            onClick={handleAddUrl}
            className="px-2 py-1 bg-gray-700 rounded text-xs hover:bg-gray-600"
          >
            Add
          </button>
        </div>
        
        {/* Results */}
        {results.length > 0 ? (
          <div className="space-y-1">
            {results.map(({ url, matches }, i) => (
              <div 
                key={i}
                className={`flex items-center gap-2 px-2 py-1 rounded text-xs font-mono ${
                  matches 
                    ? 'bg-green-900/20 border border-green-700/30' 
                    : 'bg-red-900/20 border border-red-700/30'
                }`}
              >
                {matches ? (
                  <Check size={12} className="text-green-400" />
                ) : (
                  <X size={12} className="text-red-400" />
                )}
                <span className="flex-1 truncate">{url}</span>
                <span className={matches ? 'text-green-400' : 'text-red-400'}>
                  {matches ? 'MATCHES' : 'NO MATCH'}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-gray-500 italic">
            Add URLs to test the pattern
          </div>
        )}
      </div>
    </div>
  );
}


