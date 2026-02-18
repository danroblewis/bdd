#!/usr/bin/env python3
"""Simple MCP server that returns the current time."""

import asyncio
import json
import sys
from datetime import datetime, timezone


async def handle_request(request: dict) -> dict:
    """Handle an MCP request."""
    method = request.get("method")
    req_id = request.get("id")
    
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "time-server",
                    "version": "1.0.0"
                }
            }
        }
    
    elif method == "notifications/initialized":
        # No response needed for notifications
        return None
    
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "get_current_time",
                        "description": "Get the current time in various formats",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "timezone": {
                                    "type": "string",
                                    "description": "Timezone name (e.g., 'UTC', 'US/Pacific'). Default is UTC.",
                                    "default": "UTC"
                                },
                                "format": {
                                    "type": "string", 
                                    "description": "Output format: 'iso', 'human', 'unix'. Default is 'human'.",
                                    "default": "human"
                                }
                            },
                            "required": []
                        }
                    },
                    {
                        "name": "get_timestamp",
                        "description": "Get the current Unix timestamp (seconds since epoch)",
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                ]
            }
        }
    
    elif method == "tools/call":
        tool_name = request.get("params", {}).get("name")
        arguments = request.get("params", {}).get("arguments", {})
        
        if tool_name == "get_current_time":
            tz_name = arguments.get("timezone", "UTC")
            fmt = arguments.get("format", "human")
            
            try:
                if tz_name == "UTC":
                    now = datetime.now(timezone.utc)
                else:
                    # Try to use zoneinfo for other timezones
                    try:
                        from zoneinfo import ZoneInfo
                        now = datetime.now(ZoneInfo(tz_name))
                    except:
                        now = datetime.now(timezone.utc)
                        tz_name = "UTC (fallback)"
                
                if fmt == "iso":
                    time_str = now.isoformat()
                elif fmt == "unix":
                    time_str = str(int(now.timestamp()))
                else:  # human
                    time_str = now.strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
                
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Current time ({tz_name}): {time_str}"
                            }
                        ]
                    }
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {e}"}],
                        "isError": True
                    }
                }
        
        elif tool_name == "get_timestamp":
            timestamp = int(datetime.now(timezone.utc).timestamp())
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": str(timestamp)
                        }
                    ]
                }
            }
        
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Unknown tool: {tool_name}"
                }
            }
    
    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }


async def main():
    """Main loop - read from stdin, write to stdout."""
    print("Time MCP Server started", file=sys.stderr)
    
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)
    
    writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout
    )
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_event_loop())
    
    buffer = ""
    
    while True:
        try:
            chunk = await reader.read(4096)
            if not chunk:
                break
            
            buffer += chunk.decode('utf-8')
            
            # Process complete messages (newline-delimited JSON)
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.strip()
                if not line:
                    continue
                
                try:
                    request = json.loads(line)
                    print(f"Received: {request.get('method', 'unknown')}", file=sys.stderr)
                    
                    response = await handle_request(request)
                    
                    if response is not None:
                        response_str = json.dumps(response) + '\n'
                        writer.write(response_str.encode('utf-8'))
                        await writer.drain()
                        print(f"Sent response for: {request.get('method', 'unknown')}", file=sys.stderr)
                
                except json.JSONDecodeError as e:
                    print(f"JSON decode error: {e}", file=sys.stderr)
                    
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            break
    
    print("Time MCP Server stopped", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())

