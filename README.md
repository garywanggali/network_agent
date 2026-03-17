# HTTP/HTTPS 代理（Flask）

基于 Flask 的简易 HTTP 代理，同时支持 **HTTP** 与 **HTTPS（CONNECT 隧道）**。

## 安装

```bash
# 建议使用虚拟环境
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 运行

```bash
python proxy.py
```

默认监听 `0.0.0.0:8080`。

## 使用方式

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

## 说明

- **HTTP**：代理接收完整 HTTP 请求，转发到目标服务器并返回响应（由 Flask + requests 处理）。
- **HTTPS**：使用标准 `CONNECT` 隧道：代理与目标建立 TCP 连接后，在客户端与目标之间双向转发加密数据，不解密内容。
- 本代理不校验上游 SSL 证书（`verify=False`），仅作本地或内网转发时使用。
