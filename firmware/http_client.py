# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

# Minimal verified-HTTPS client with a persistent keep-alive connection.
#
# The bundled `requests` module has no way to supply a TLS context and does
# NOT verify server certificates by default. This client verifies the chain
# against our pinned roots (certificate_authorities.py) and checks the
# hostname, so the badge refuses to talk to anything that cannot prove it is
# the stats server — the access token never goes to an impostor (DNS hijack,
# on-path interception, captive portal, ...). Failing closed here is the
# fetch-side security boundary.
#
# Why persistent: the TLS handshake costs ~1.8 s on the badge, but a GET on
# an already-established connection measured 73-90 ms (small feeds) / ~215 ms
# (claude-stats.json) — cheap enough to run synchronously from the input
# loop. The server (nginx) holds keep-alive connections ~65 s and frames
# static-file responses with Content-Length, so HTTP/1.1 reuse is simple.

import json
import socket

import tls

from certificate_authorities import TRUSTED_ROOT_CERTIFICATES_DER

RESPONSE_CHUNK_BYTES = 4096


class HttpError(Exception):
    pass


def split_url(url):
    # "https://host[:port]/path?query" -> (host, port, "/path?query")
    if not url.startswith("https://"):
        raise HttpError("only https:// urls are allowed: " + url)
    remainder = url[len("https://"):]
    slash_index = remainder.find("/")
    if slash_index == -1:
        host_and_port, path = remainder, "/"
    else:
        host_and_port, path = remainder[:slash_index], remainder[slash_index:]
    if ":" in host_and_port:
        host, port_text = host_and_port.split(":", 1)
        return host, int(port_text), path
    return host_and_port, 443, path


def build_tls_context():
    context = tls.SSLContext(tls.PROTOCOL_TLS_CLIENT)
    context.verify_mode = tls.CERT_REQUIRED
    # MicroPython's load_verify_locations takes cadata as its only, positional
    # argument (unlike CPython) and parses DER, one certificate per call —
    # repeated calls append to the trusted set.
    for trusted_root_der in TRUSTED_ROOT_CERTIFICATES_DER:
        context.load_verify_locations(trusted_root_der)
    return context


class PersistentConnection:
    """One keep-alive TLS connection to the stats server.

    `get()` reuses the established socket and transparently reconnects once
    when a kept-alive socket turns out to be stale (the server idle-closes
    after ~65 s, and closes after its keep-alive request budget). A failed
    CONNECT is raised to the caller — backoff policy lives in feeds.py, next
    to the cadences.
    """

    def __init__(self, base_url, connect_timeout_seconds=20, request_timeout_seconds=10):
        self.host, self.port, _ = split_url(base_url)
        self.connect_timeout_seconds = connect_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self._tls_context = build_tls_context()
        self._socket = None

    @property
    def is_connected(self):
        return self._socket is not None

    def connect(self):
        """Dial + TLS handshake (~1.8 s on the badge). Idempotent."""
        if self._socket is not None:
            return
        address = socket.getaddrinfo(
            self.host, self.port, 0, socket.SOCK_STREAM
        )[0][-1]
        plain_socket = socket.socket()
        plain_socket.settimeout(self.connect_timeout_seconds)
        try:
            plain_socket.connect(address)
            # wrap_socket performs the handshake including chain + hostname checks.
            secure_socket = self._tls_context.wrap_socket(
                plain_socket, server_hostname=self.host
            )
        except Exception:
            plain_socket.close()
            raise
        plain_socket.settimeout(self.request_timeout_seconds)
        self._socket = secure_socket

    def close(self):
        if self._socket is None:
            return
        try:
            self._socket.close()
        except OSError:
            pass
        self._socket = None

    def get(self, path):
        """Keep-alive GET. Returns (status_code, body_bytes).

        On a reused socket an OSError means the server closed it between
        requests — retried once on a fresh connection. Errors on a fresh
        connection propagate (the server/network is actually down).
        """
        socket_was_warm = self.is_connected
        self.connect()
        try:
            return self._request(path)
        except OSError:
            self.close()
            if not socket_was_warm:
                raise
        except Exception:
            # protocol-level surprise mid-response — the socket is desynced
            self.close()
            raise
        self.connect()
        try:
            return self._request(path)
        except Exception:
            self.close()
            raise

    def get_json(self, path):
        """Keep-alive GET; parses the body as JSON on 200.
        Returns (status_code, payload_or_None, body_bytes_or_None)."""
        status_code, body = self.get(path)
        if status_code != 200:
            return status_code, None, None
        return status_code, json.loads(body), body

    def _request(self, path):
        request_text = (
            "GET " + path + " HTTP/1.1\r\n"
            "Host: " + self.host + "\r\n"
            "Connection: keep-alive\r\n"
            "\r\n"
        )
        self._socket.write(request_text.encode())

        status_line = self._socket.readline()
        if not status_line:
            raise OSError("connection closed before response")
        status_code = int(status_line.split(b" ")[1])

        content_length = None
        server_will_close = False
        while True:
            header_line = self._socket.readline()
            if not header_line:
                raise OSError("connection closed in headers")
            if header_line == b"\r\n":
                break
            header_lower = header_line.lower()
            if header_lower.startswith(b"content-length:"):
                content_length = int(header_line.split(b":", 1)[1])
            elif header_lower.startswith(b"connection:") and b"close" in header_lower:
                server_will_close = True
            elif header_lower.startswith(b"transfer-encoding:") and b"chunked" in header_lower:
                # nginx frames static files (our feeds) with Content-Length;
                # chunked would mean a different server — fail loudly.
                raise HttpError("chunked responses are not supported")
        if content_length is None:
            raise HttpError("response has no content-length")

        body = b""
        while len(body) < content_length:
            chunk = self._socket.read(min(RESPONSE_CHUNK_BYTES, content_length - len(body)))
            if not chunk:
                raise OSError("connection closed in body")
            body += chunk

        if server_will_close:
            self.close()
        return status_code, body
