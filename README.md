# network_agent

网络代理工具，提供两种部署方式：

1. **HTTP/HTTPS 代理**（`proxy.py`）- 基于 Flask
2. **Shadowsocks 代理**（`run_shadowsocks.sh`）- 加密 SOCKS5 隧道

---

## 方式一：HTTP/HTTPS 代理（Flask）

基于 Flask 的简易 HTTP 代理，同时支持 **HTTP** 与 **HTTPS（CONNECT 隧道）**。

### 安装

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 运行

```bash
python proxy.py
```

默认监听 `0.0.0.0:8080`。

### 使用方式

将浏览器或系统代理设置为：

- **地址**: `127.0.0.1`（本机）或你的机器 IP
- **端口**: `8080`

### 测试 HTTP

```bash
curl -x http://127.0.0.1:8080 http://httpbin.org/get
```

### 测试 HTTPS

```bash
curl -x http://127.0.0.1:8080 https://httpbin.org/get
```

### 说明

- **HTTP**：代理接收完整 HTTP 请求，转发到目标服务器并返回响应（由 Flask + requests 处理）。
- **HTTPS**：使用标准 `CONNECT` 隧道：代理与目标建立 TCP 连接后，在客户端与目标之间双向转发加密数据，不解密内容。
- 本代理不校验上游 SSL 证书（`verify=False`），仅作本地或内网转发时使用。

---

## 方式二：Shadowsocks 代理

Shadowsocks 是一种加密的 SOCKS5 代理，客户端需使用 Shadowsocks 客户端（如 Clash、V2Ray、Outline 等）连接。

### 安装

```bash
pip install -r requirements-shadowsocks.txt
```

### 配置

编辑 `shadowsocks_config.json`：

```json
{
  "server": "0.0.0.0",
  "server_port": 8388,
  "password": "你的密码",
  "method": "aes-256-gcm"
}
```

- `server_port`：服务端监听端口（默认 8388）
- `password`：客户端连接密码，需与客户端配置一致
- `method`：加密方式，推荐 `aes-256-gcm`，若报错可改为 `aes-256-cfb`

### 运行

```bash
chmod +x run_shadowsocks.sh
./run_shadowsocks.sh
```

或直接用命令：

```bash
ssserver -c shadowsocks_config.json
```

### 使用方式

客户端需使用 Shadowsocks 协议连接，配置示例：

- **服务器地址**：你的服务器公网 IP
- **端口**：`8388`
- **密码**：与 `shadowsocks_config.json` 中的 `password` 一致
- **加密方式**：与 `method` 一致（如 `aes-256-gcm`）

### 说明

- Shadowsocks 在传输层加密，适合对隐私要求更高的场景。
- 客户端推荐：Shadowsocks 官方客户端、Clash、V2Ray、Outline 等。
- 若 `shadowsocks-py` 在 Python 3.14 上导入报错，可尝试 Python 3.9–3.12 的虚拟环境，或使用 Docker 部署 shadowsocks-libev。
- 若 `shadowsocks-py` 在当前 Python 版本上报错，可尝试 Python 3.9–3.12 的虚拟环境，或使用 Docker 部署 shadowsocks 服务。
