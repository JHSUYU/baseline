"""Egress proxy for the coding-agent containers: HTTP CONNECT only, to an allowlist of Anthropic hosts.

The agent containers sit on an internal Docker network with no route out; this proxy is their only way
out, so the agent can reach the model API but no web page, issue tracker or code host.  Every request,
allowed or refused, is logged with its host.
"""
import asyncio, os, sys, time

ALLOW_SUFFIXES = (".anthropic.com", ".claude.com", ".claude.ai")
ALLOW_EXACT = {"anthropic.com", "claude.com", "claude.ai"}
PORT = int(os.environ.get("PROXY_PORT", "3128"))


def allowed(host):
    host = host.lower().rstrip(".")
    return host in ALLOW_EXACT or host.endswith(ALLOW_SUFFIXES)


def log(msg):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg, flush=True)


async def pipe(r, w):
    try:
        while True:
            data = await r.read(65536)
            if not data:
                break
            w.write(data)
            await w.drain()
    except Exception:
        pass
    finally:
        try:
            w.close()
        except Exception:
            pass


async def handle(cr, cw):
    peer = cw.get_extra_info("peername")
    try:
        head = await asyncio.wait_for(cr.readuntil(b"\r\n\r\n"), 30)
    except Exception:
        cw.close()
        return
    line = head.split(b"\r\n", 1)[0].decode("latin-1")
    parts = line.split()
    if len(parts) < 2 or parts[0].upper() != "CONNECT":
        log(f"DENY non-CONNECT {line!r} from {peer}")
        cw.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        await cw.drain(); cw.close(); return
    host, _, port = parts[1].rpartition(":")
    if not allowed(host) or port != "443":
        log(f"DENY {host}:{port} from {peer}")
        cw.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        await cw.drain(); cw.close(); return
    try:
        ur, uw = await asyncio.wait_for(asyncio.open_connection(host, 443), 30)
    except Exception as e:
        log(f"FAIL {host}:443 {e}")
        cw.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        await cw.drain(); cw.close(); return
    log(f"ALLOW {host}:443 from {peer}")
    cw.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
    await cw.drain()
    await asyncio.gather(pipe(cr, uw), pipe(ur, cw))


async def main():
    srv = await asyncio.start_server(handle, "0.0.0.0", PORT)
    log(f"listening on {PORT}")
    async with srv:
        await srv.serve_forever()

asyncio.run(main())
