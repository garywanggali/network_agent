"""
HTTP/HTTPS 代理服务器（基于 Flask + 原始 socket 处理 CONNECT）

- HTTP：由 Flask 接收请求并转发到目标服务器
- HTTPS：使用 CONNECT 隧道，代理与目标建立 TCP 连接后双向转发数据
"""

import json
import socket
import threading
from urllib.parse import urlparse
from io import BytesIO

from flask import Flask, request, Response
import requests

app = Flask(__name__)

# 请求时不要验证 SSL（代理场景常用）
SESSION = requests.Session()
SESSION.verify = False
# 转发时直连目标，不使用环境变量里的代理，避免形成代理循环或 502
SESSION.trust_env = False
# 忽略 InsecureRequestWarning
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def proxy_http():
    """处理 HTTP 请求：从请求中取出目标 URL 并转发。"""
    # 客户端会发 GET http://example.com/path HTTP/1.1
    url = request.url
    if not url.startswith("http"):
        # 某些客户端可能只发 path，用 Host 拼成完整 URL
        url = request.host_url.rstrip("/") + (request.path or "/")
        if request.query_string:
            url += "?" + request.query_string.decode("utf-8")

    method = request.method
    headers = {k: v for k, v in request.headers if k.lower() not in ("host", "connection", "proxy-connection")}
    # 加上自定义头，目标站（如 httpbin）会原样回显，用来证明请求是经代理转发的
    headers["X-Via-Proxy"] = "127.0.0.1:8080 (via proxy)"
    data = request.get_data() if request.get_data() else None

    try:
        resp = SESSION.request(
            method,
            url,
            headers=headers,
            data=data,
            allow_redirects=False,
            timeout=30,
        )
        excluded = ("transfer-encoding", "content-encoding", "content-length", "connection")
        response_headers = [
            (k, v) for k, v in resp.raw.headers.items()
            if k.lower() not in excluded
        ]
        # 响应头里也加一份，方便在浏览器开发者工具里看到
        response_headers.append(("X-Via-Proxy", "127.0.0.1:8080 (via proxy)"))

        body = resp.content
        # 若是 httpbin 的 JSON，在 body 里注入 via_proxy，页面上直接能看到
        content_type = (resp.headers.get("Content-Type") or "").lower()
        if "application/json" in content_type and "httpbin.org" in url:
            try:
                obj = json.loads(body.decode("utf-8", errors="replace"))
                obj["via_proxy"] = "127.0.0.1:8080 (via proxy)"
                body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
                # 更新 Content-Length
                response_headers = [(k, v) for k, v in response_headers if k.lower() != "content-length"]
                response_headers.append(("Content-Length", str(len(body))))
            except Exception:
                pass

        return Response(body, status=resp.status_code, headers=response_headers)
    except Exception as e:
        return Response(str(e), status=502)


# 让 Flask 把所有请求都交给代理逻辑
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def proxy(path):
    return proxy_http()


def read_until_crlf_crlf(sock, max_headers=8192):
    """从 socket 读到 \\r\\n\\r\\n，返回已读的字节。"""
    buf = b""
    while len(buf) < max_headers:
        chunk = sock.recv(1)
        if not chunk:
            break
        buf += chunk
        if buf.endswith(b"\r\n\r\n"):
            break
    return buf


def parse_request_line(line):
    """解析首行，返回 (method, url_or_host, version)。"""
    parts = line.strip().split()
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    return None, None, None


def handle_connect_tunnel(client_socket, first_chunk=None):
    """处理 HTTPS CONNECT：与目标建立连接后双向转发。first_chunk 若提供，则已包含首行+headers，不再从 socket 读。"""
    try:
        if first_chunk:
            raw = first_chunk
        else:
            raw = read_until_crlf_crlf(client_socket)
        if not raw:
            client_socket.close()
            return
        first_line = raw.split(b"\r\n")[0].decode("utf-8", errors="replace")
        method, target, _ = parse_request_line(first_line)
        if method != "CONNECT" or not target:
            client_socket.close()
            return

        if ":" in target:
            host, port_str = target.rsplit(":", 1)
            port = int(port_str)
        else:
            host, port = target, 443

        remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        remote.settimeout(30)
        try:
            remote.connect((host, port))
        except Exception as e:
            reply = (
                b"HTTP/1.1 502 Bad Gateway\r\n"
                b"Content-Type: text/plain\r\n"
                b"Connection: close\r\n\r\n"
                b"Proxy could not connect: " + str(e).encode("utf-8")
            )
            client_socket.sendall(reply)
            client_socket.close()
            return

        client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

        def forward(src, dst):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    dst.sendall(data)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        t1 = threading.Thread(target=forward, args=(client_socket, remote))
        t2 = threading.Thread(target=forward, args=(remote, client_socket))
        t1.daemon = True
        t2.daemon = True
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except Exception:
        pass
    finally:
        try:
            client_socket.close()
        except OSError:
            pass
        try:
            remote.close()
        except NameError:
            pass
        except OSError:
            pass


def run_wsgi_with_request(client_socket, full_request_bytes, app_wsgi):
    """用完整请求字节串构造 WSGI 请求，调用 app，把响应写回 client_socket。"""
    from wsgiref.util import request_uri
    import io

    raw = full_request_bytes
    first_line = raw.split(b"\r\n")[0].decode("utf-8", errors="replace")
    parts = first_line.split()
    if len(parts) < 3:
        client_socket.close()
        return
    method, path, version = parts[0], parts[1], parts[2]

    if path.startswith("http://") or path.startswith("https://"):
        parsed = urlparse(path)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        host = parsed.netloc
    else:
        host = None

    headers_end = raw.find(b"\r\n\r\n")
    headers_blob = raw[:headers_end]
    body_start = headers_end + 4
    headers = {}
    for line in headers_blob.split(b"\r\n")[1:]:
        if b":" in line:
            k, v = line.split(b":", 1)
            headers[k.strip().decode("utf-8", errors="replace")] = v.strip().decode("utf-8", errors="replace")
    if not host and "Host" in headers:
        host = headers["Host"]

    content_length = int(headers.get("Content-Length", 0))
    body = raw[body_start:body_start + content_length] if content_length else raw[body_start:]

    environ = {
        "REQUEST_METHOD": method,
        "SCRIPT_NAME": "",
        "PATH_INFO": path.split("?")[0] if "?" in path else path,
        "QUERY_STRING": path.split("?", 1)[1] if "?" in path else "",
        "SERVER_NAME": (host or "localhost").split(":")[0],
        "SERVER_PORT": (host or "localhost").split(":")[-1] if host and ":" in host else "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": BytesIO(body),
        "wsgi.errors": io.BytesIO(),
        "wsgi.version": (1, 0),
        "wsgi.run_once": False,
        "wsgi.multithread": True,
        "wsgi.multiprocess": False,
        "wsgi.url_scheme": "http",
    }
    for k, v in headers.items():
        key = "HTTP_" + k.upper().replace("-", "_")
        environ[key] = v

    status_sent = [None]
    headers_sent = [None]

    def start_response(status, response_headers):
        status_sent[0] = status
        headers_sent[0] = response_headers

    result = app_wsgi(environ, start_response)
    response_body = b"".join(result)
    status = status_sent[0] or "200 OK"
    response_headers = headers_sent[0] or []

    code = status.split(None, 1)[0] if status else "200"
    reason = status.split(None, 1)[1] if len(status.split(None, 1)) > 1 else "OK"
    out = f"HTTP/1.1 {code} {reason}\r\n".encode("utf-8")
    for k, v in response_headers:
        out += f"{k}: {v}\r\n".encode("utf-8")
    out += b"\r\n"
    out += response_body
    try:
        client_socket.sendall(out)
    except OSError:
        pass
    finally:
        client_socket.close()


def handle_connection(client_socket, app_wsgi):
    """判断是 CONNECT 还是普通 HTTP，分别处理。"""
    first_chunk = None
    try:
        client_socket.settimeout(10)
        first_chunk = read_until_crlf_crlf(client_socket)
        if not first_chunk:
            client_socket.close()
            return
        first_line = first_chunk.split(b"\r\n")[0].decode("utf-8", errors="replace")
        method, _, _ = parse_request_line(first_line)

        if method == "CONNECT":
            handle_connect_tunnel(client_socket, first_chunk=first_chunk)
        else:
            # 已读首行+headers，可能还有 body
            headers_end = first_chunk.find(b"\r\n\r\n")
            if headers_end == -1:
                client_socket.close()
                return
            headers_blob = first_chunk[:headers_end]
            body_start = headers_end + 4
            headers_dict = {}
            for line in headers_blob.split(b"\r\n")[1:]:
                if b":" in line:
                    k, v = line.split(b":", 1)
                    headers_dict[k.strip().decode()] = v.strip().decode()
            cl = int(headers_dict.get("Content-Length", 0))
            rest = first_chunk[body_start:]
            while len(rest) < cl:
                chunk = client_socket.recv(65536)
                if not chunk:
                    break
                rest += chunk
            rest = rest[:cl]
            full_request = first_chunk[:body_start + cl] if cl else first_chunk
            run_wsgi_with_request(client_socket, full_request, app_wsgi)
    except Exception:
        try:
            client_socket.close()
        except OSError:
            pass


def main():
    host = "0.0.0.0"
    port = 8080
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(128)
    print(f"Proxy listening on http://{host}:{port} (HTTP + HTTPS CONNECT)")

    app_wsgi = app.wsgi_app

    while True:
        client_socket, addr = server_socket.accept()
        t = threading.Thread(target=handle_connection, args=(client_socket, app_wsgi))
        t.daemon = True
        t.start()


if __name__ == "__main__":
    main()
