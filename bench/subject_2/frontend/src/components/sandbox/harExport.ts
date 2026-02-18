/**
 * HAR (HTTP Archive) export functionality for network monitoring.
 * 
 * Exports network requests in HAR 1.2 format with sandbox-specific
 * custom fields for source attribution.
 */

import type { NetworkRequest } from '../../utils/types';

interface HARLog {
  version: string;
  creator: {
    name: string;
    version: string;
  };
  entries: HAREntry[];
}

interface HAREntry {
  startedDateTime: string;
  time: number;
  request: {
    method: string;
    url: string;
    httpVersion: string;
    cookies: any[];
    headers: Array<{ name: string; value: string }>;
    queryString: any[];
    headersSize: number;
    bodySize: number;
  };
  response: {
    status: number;
    statusText: string;
    httpVersion: string;
    cookies: any[];
    headers: any[];
    content: {
      size: number;
      mimeType: string;
    };
    redirectURL: string;
    headersSize: number;
    bodySize: number;
  };
  cache: {};
  timings: {
    wait: number;
    receive: number;
  };
  _sandbox_source: string;
  _sandbox_matched_pattern?: string;
  _sandbox_is_llm_provider: boolean;
}

function statusToText(status: number): string {
  const statusTexts: Record<number, string> = {
    200: 'OK',
    201: 'Created',
    204: 'No Content',
    301: 'Moved Permanently',
    302: 'Found',
    304: 'Not Modified',
    400: 'Bad Request',
    401: 'Unauthorized',
    403: 'Forbidden',
    404: 'Not Found',
    500: 'Internal Server Error',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
  };
  return statusTexts[status] || 'Unknown';
}

export function convertToHAR(requests: NetworkRequest[], appName: string = 'ADK Playground'): HARLog {
  const entries: HAREntry[] = requests.map((req) => {
    const headers: Array<{ name: string; value: string }> = [];
    if (req.headers) {
      for (const [name, value] of Object.entries(req.headers)) {
        headers.push({ name, value });
      }
    }
    
    return {
      startedDateTime: req.timestamp,
      time: req.response_time_ms || 0,
      request: {
        method: req.method,
        url: req.url,
        httpVersion: 'HTTP/1.1',
        cookies: [],
        headers,
        queryString: [],
        headersSize: -1,
        bodySize: -1,
      },
      response: {
        status: req.response_status || (req.status === 'denied' ? 403 : 0),
        statusText: statusToText(req.response_status || 0),
        httpVersion: 'HTTP/1.1',
        cookies: [],
        headers: [],
        content: {
          size: req.response_size || 0,
          mimeType: 'application/octet-stream',
        },
        redirectURL: '',
        headersSize: -1,
        bodySize: req.response_size || -1,
      },
      cache: {},
      timings: {
        wait: req.response_time_ms || 0,
        receive: 0,
      },
      // Custom sandbox fields
      _sandbox_source: req.source,
      _sandbox_matched_pattern: req.matched_pattern,
      _sandbox_is_llm_provider: req.is_llm_provider,
    };
  });
  
  return {
    version: '1.2',
    creator: {
      name: appName,
      version: '1.0',
    },
    entries,
  };
}

export function downloadHAR(requests: NetworkRequest[], filename?: string): void {
  const har = { log: convertToHAR(requests) };
  const blob = new Blob([JSON.stringify(har, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  
  const a = document.createElement('a');
  a.href = url;
  a.download = filename || `sandbox-network-${new Date().toISOString().slice(0, 10)}.har`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}


