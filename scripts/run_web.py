#!/usr/bin/env python3
"""管理本次启动的 API / Next.js 进程组，不接管已有服务，不检查模型就绪状态。"""

import argparse
from http.client import HTTPConnection, HTTPException
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import cast
from urllib.parse import urlsplit


class StopRequested(Exception):
    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum: int = signum


class WebArguments(argparse.Namespace):
    api_port: int = 8000
    port: int = 3000
    timeout: float = 30.0


def port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("端口必须是整数") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口范围为 1 到 65535")
    return port


def available_port(port: int) -> None:
    """启动前拒绝已占用端口，避免把其他 API 的健康响应当成本次启动成功。"""
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as error:
            raise RuntimeError(f"本机端口 {port} 不可用，请指定其他端口或先关闭已有服务。") from error


def wait_for_api(process: subprocess.Popen[bytes], url: str, timeout: float) -> None:
    """只探测 /health 存活；模型未配置时也允许打开 Web 配置页面。"""
    deadline = time.monotonic() + timeout
    origin = urlsplit(url)
    host = origin.hostname
    if host is None or origin.scheme != "http":
        raise ValueError("API 存活检查需要本机 HTTP origin")
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"API 在启动完成前退出，状态码 {process.returncode}。")
        remaining = max(0.01, deadline - time.monotonic())
        connection = HTTPConnection(host, origin.port, timeout=min(0.5, remaining))
        try:
            connection.request("GET", "/health")
            with connection.getresponse() as response:
                payload = cast(object, json.loads(response.read(1024)))
                healthy = response.status == 200 and payload == {"status": "ok"}
            if healthy and process.poll() is None:
                return
        except (OSError, HTTPException, ValueError):
            pass
        finally:
            connection.close()
        time.sleep(0.1)
    raise RuntimeError(f"等待 API 存活超时（{timeout:g} 秒）。")


def stop_processes(processes: list[subprocess.Popen[bytes]]) -> None:
    """只向本次创建的进程组发送信号，领进程退出后也清理其残留子进程。"""
    for process in reversed(processes):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    # uv/npm 的领进程可能先退出，仍须给组内的实际服务留出清理时间。
    while time.monotonic() < deadline:
        active = False
        for process in processes:
            _ = process.poll()
            try:
                os.killpg(process.pid, 0)
                active = True
            except ProcessLookupError:
                pass
        if not active:
            break
        time.sleep(0.05)
    for process in reversed(processes):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _ = process.wait()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--api-port", type=port_number, default=os.environ.get("OMT_API_PORT", "8000"))
    _ = parser.add_argument("--port", type=port_number, default=os.environ.get("OMT_WEB_PORT", "3000"), help="前端端口")
    _ = parser.add_argument("--timeout", type=float, default=30, help="API 启动等待秒数，默认 30")
    args = parser.parse_args(namespace=WebArguments())
    if not 0 < args.timeout < float("inf"):
        parser.error("--timeout 必须是有限正数")
    if args.api_port == args.port:
        parser.error("API 和前端需要不同端口")
    processes: list[subprocess.Popen[bytes]] = []

    def stop(signum: int, _frame: object) -> None:
        raise StopRequested(signum)

    old_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        for command in ("uv", "node", "npm"):
            if shutil.which(command) is None:
                raise RuntimeError(f"缺少 {command}，请先安装后运行 scripts/setup.sh。")
        if not (root / "backend" / ".venv" / "bin" / "python").is_file():
            raise RuntimeError("后端依赖未安装，请运行 scripts/setup.sh。")
        if not (root / "frontend" / "node_modules" / "next").is_dir():
            raise RuntimeError("前端依赖未安装，请运行 scripts/setup.sh。")
        available_port(args.api_port)
        available_port(args.port)
        backend_url = f"http://127.0.0.1:{args.api_port}"
        api = subprocess.Popen([str(root / "scripts" / "start-api.sh"), "--port", str(args.api_port)],
                               start_new_session=True)
        processes.append(api)
        wait_for_api(api, backend_url, args.timeout)
        frontend_env = dict(os.environ, OMT_BACKEND_URL=backend_url)
        web = subprocess.Popen(["npm", "run", "dev", "--", "--port", str(args.port)],
                               cwd=root / "frontend", env=frontend_env, start_new_session=True)
        processes.append(web)
        print(f"API：{backend_url}\nWeb 启动中：http://127.0.0.1:{args.port}\nCtrl+C 关闭本次启动的两个进程。", flush=True)
        while True:
            for name, process in (("API", api), ("Web", web)):
                status = process.poll()
                if status is not None:
                    raise RuntimeError(f"{name} 已退出，状态码 {status}。")
            time.sleep(0.2)
    except StopRequested as requested:
        return 128 + requested.signum
    except (OSError, RuntimeError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
    finally:
        for sig in old_handlers:
            _ = signal.signal(sig, signal.SIG_IGN)
        stop_processes(processes)
        for sig, handler in old_handlers.items():
            _ = signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
