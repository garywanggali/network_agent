#!/bin/bash
# Shadowsocks 服务端启动脚本
# 使用前: pip install -r requirements-shadowsocks.txt

cd "$(dirname "$0")"
exec ssserver -c shadowsocks_config.json
