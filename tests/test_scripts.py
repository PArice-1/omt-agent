"""通过隔离命令、临时项目和真实子进程验证脚本，不读取用户配置或调用模型。"""

from functools import cached_property
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from typing import TypedDict, cast
import unittest
from unittest.mock import MagicMock, patch

from scripts import run_web


SOURCE = Path(__file__).resolve().parents[1]


class CommandEvent(TypedDict):
    name: str
    pid: int
    args: list[str]
    cwd: str
    backend_url: str | None


FAKE_COMMAND = '''import json, os, signal, subprocess, sys, time
from pathlib import Path
name = Path(sys.argv[0]).name
event = {"name": name, "args": sys.argv[1:], "cwd": os.getcwd(), "pid": os.getpid(),
         "backend_url": os.environ.get("OMT_BACKEND_URL")}
def record(value):
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(json.dumps(value) + "\\n")
record(event)
is_api = name == "uv" and "uvicorn" in sys.argv
is_web = name == "npm" and "dev" in sys.argv
if not (is_api or is_web):
    sys.exit(0)
if is_api and os.environ.get("FAKE_API_MODE") == "exit":
    sys.exit(9)
if is_web and os.environ.get("FAKE_WEB_MODE") == "exit":
    sys.exit(7)
worker = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
record({"name": "worker", "pid": worker.pid, "parent": os.getpid()})
def stop(signum, frame):
    worker.terminate()
    worker.wait(timeout=3)
    sys.exit(128 + signum)
signal.signal(signal.SIGTERM, stop)
if is_api and os.environ.get("FAKE_NETWORK") == "1":
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"status":"ok"}' if self.path == "/health" else b'{"ready":false}'
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args): pass
    port = int(sys.argv[sys.argv.index("--port") + 1])
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
else:
    while True: time.sleep(0.05)
'''


ISOLATED_RUNNER = '''import importlib.util, json, os, sys, time
from pathlib import Path
root = Path(__file__).parent
spec = importlib.util.spec_from_file_location("web", root / "scripts/run_web.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
# 进程编排测试用文件就绪替身隔离网络；真实 HTTP 检查由独立测试覆盖。
module.available_port = lambda port: None
def ready(process, url, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None: raise RuntimeError("API 启动失败")
        if os.environ.get("FAKE_API_MODE") != "hang":
            log = Path(os.environ["FAKE_LOG"])
            if log.exists() and '"name": "worker"' in log.read_text(): return
        time.sleep(0.02)
    raise RuntimeError("API 存活超时")
module.wait_for_api = ready
sys.exit(module.main())
'''


def sockets_available() -> bool:
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
        return True
    except OSError:
        return False


class ScriptTests(unittest.TestCase):
    @cached_property
    def base(self) -> Path:
        temporary = tempfile.TemporaryDirectory(prefix="omt-scripts-")
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    @property
    def root(self) -> Path:
        return self.base / "repo with spaces"

    @property
    def workspace(self) -> Path:
        return self.base / "user workspace"

    @property
    def bin(self) -> Path:
        return self.base / "bin"

    @property
    def log(self) -> Path:
        return self.base / "events.jsonl"

    @cached_property
    def env(self) -> dict[str, str]:
        values = {name: value for name, value in os.environ.items() if not name.startswith("OMT_")}
        values.update(PATH=str(self.bin) + os.pathsep + os.environ["PATH"], FAKE_LOG=str(self.log))
        return values

    def setUp(self) -> None:
        shutil.copytree(SOURCE / "scripts", self.root / "scripts")
        self.workspace.mkdir()
        self.bin.mkdir()
        for name in ("uv", "npm", "node"):
            executable = self.bin / name
            executable.write_text(f"#!{sys.executable}\n" + FAKE_COMMAND)
            executable.chmod(0o755)
        interpreter = self.root / "backend/.venv/bin/python"
        interpreter.parent.mkdir(parents=True)
        interpreter.symlink_to(sys.executable)
        (self.root / "frontend/node_modules/next").mkdir(parents=True)
        (self.root / "isolated_runner.py").write_text(ISOLATED_RUNNER)

    def events(self) -> list[CommandEvent]:
        if not self.log.exists():
            return []
        result: list[CommandEvent] = []
        for line in self.log.read_text().splitlines():
            try:
                payload = cast(object, json.loads(line))
            except json.JSONDecodeError:
                continue
            assert isinstance(payload, dict)
            record = cast(dict[str, object], payload)
            name, pid = record["name"], record["pid"]
            args, cwd = record.get("args", []), record.get("cwd", "")
            url = record.get("backend_url")
            assert isinstance(name, str) and isinstance(pid, int)
            assert isinstance(args, list) and isinstance(cwd, str)
            assert all(isinstance(value, str) for value in cast(list[object], args))
            assert url is None or isinstance(url, str)
            result.append({"name": name, "pid": pid, "args": cast(list[str], args),
                           "cwd": cwd, "backend_url": url})
        return result

    def run_script(self, name: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(self.root / "scripts" / name), *args], cwd=self.workspace,
                              env=self.env, capture_output=True, text=True, timeout=10)

    def launch_web(self, *args: str, network: bool = False) -> subprocess.Popen[str]:
        command = (["bash", str(self.root / "scripts/start-web.sh")] if network else
                   [sys.executable, str(self.root / "isolated_runner.py")])
        process = subprocess.Popen([*command, *args], cwd=self.workspace, env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(self.close_process, process)
        return process

    def close_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
            self.fail("脚本未及时清理进程")

    def wait_for_web(self, process: subprocess.Popen[str]) -> None:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if any(event["name"] == "npm" and "dev" in event.get("args", []) for event in self.events()):
                return
            if process.poll() is not None:
                self.fail(process.communicate()[0])
            time.sleep(0.02)
        self.fail("前端替身未启动")

    def assert_children_stopped(self) -> None:
        for event in self.events():
            if event["name"] not in ("worker", "uv", "npm"):
                continue
            pid = event["pid"]
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            # Linux 的已退出孤儿可能等待宿主回收；它们已不执行或持有端口。
            status = Path(f"/proc/{pid}/stat")
            if status.exists() and status.read_text().split(") ", 1)[1].startswith("Z "):
                continue
            self.fail(f"测试创建的进程 {pid} 未停止")

    def test_help_needs_no_installed_backend_or_plugin(self) -> None:
        shutil.rmtree(self.root / "backend")
        for name in ("setup.sh", "start-cli.sh", "start-api.sh", "start-web.sh", "start-knowledge-base.sh"):
            with self.subTest(name=name):
                result = self.run_script(name, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.events(), [])

    def test_cli_preserves_workspace_and_forwards_arguments_without_plugin(self) -> None:
        result = self.run_script("start-cli.sh", "--plain")
        self.assertEqual(result.returncode, 0, result.stderr)
        event = self.events()[0]
        self.assertEqual(event["cwd"], str(self.workspace))
        self.assertEqual(event["args"], ["run", "--frozen", "--no-sync", "--project",
                                         str(self.root / "backend"), "omt", "--plain"])
        self.assertFalse((self.root / "knowledge_base").exists())

    def test_api_validates_and_forwards_port_preserving_workspace(self) -> None:
        # fake uv 的 uvicorn 模式会等待，因此此处只用非法参数验证未创建进程。
        for args in [("--port", "0"), ("--port", "65536"), ("--port", "abc"), ("--port",), ("--unknown",)]:
            with self.subTest(args=args):
                result = self.run_script("start-api.sh", *args)
                self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.events(), [])

    def test_missing_dependencies_produce_actionable_error(self) -> None:
        shutil.rmtree(self.root / "backend")
        result = self.run_script("start-cli.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("setup.sh", result.stderr)
        self.assertEqual(self.events(), [])

    def test_setup_installs_default_modules_and_optional_plugin(self) -> None:
        for optional in (False, True):
            with self.subTest(optional=optional):
                self.log.unlink(missing_ok=True)
                result = self.run_script("setup.sh", *(["--with-knowledge-base"] if optional else []))
                self.assertEqual(result.returncode, 0, result.stderr)
                installs = [e["args"] for e in self.events() if e["name"] == "uv"]
                expected = [["sync", "--frozen", "--project", str(self.root / "backend")]]
                if optional:
                    expected.append(["sync", "--frozen", "--project", str(self.root / "knowledge_base")])
                self.assertEqual(installs, expected)
                npm = [e for e in self.events() if e["name"] == "npm"]
                self.assertEqual(npm[0]["args"], ["ci", "--prefix", str(self.root / "frontend")])

    def test_plugin_config_is_explicit_and_does_not_write_data(self) -> None:
        source = self.base / "资料 with spaces"
        db = self.base / "db with spaces"
        for build in (False, True):
            command = [sys.executable, str(self.root / "scripts/knowledge-base-config.py"),
                       "--source", str(source), "--db-path", str(db)]
            if build:
                command.append("--build-on-start")
            result = subprocess.run(command, env=self.env, capture_output=True, text=True, check=True)
            config = json.loads(result.stdout)["knowledge"]
            self.assertEqual(config["command"], str(self.root / "scripts/start-knowledge-base.sh"))
            self.assertEqual(config["cwd"], str(self.root / "knowledge_base"))
            self.assertEqual("--build-on-start" in config["args"], build)
            self.assertEqual("--source" in config["args"], build)
        self.assertFalse(source.exists())
        self.assertFalse(db.exists())
        self.assertEqual(self.events(), [])

    def test_plugin_wrapper_uses_own_directory_and_keeps_stdout_clean(self) -> None:
        interpreter = self.root / "knowledge_base/.venv/bin/python"
        interpreter.parent.mkdir(parents=True)
        interpreter.symlink_to(sys.executable)
        result = self.run_script("start-knowledge-base.sh", "--db-path", str(self.base / "kb"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.events()[0]["cwd"], str(self.root / "knowledge_base"))
        self.assertEqual(self.events()[0]["args"][-3:], ["rag-mcp", "--db-path", str(self.base / "kb")])

    def test_web_starts_in_order_and_cleans_owned_processes_on_signal(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=signum):
                self.log.unlink(missing_ok=True)
                process = self.launch_web("--api-port", "18123", "--port", "18124")
                self.wait_for_web(process)
                calls = [e for e in self.events() if e["name"] in ("uv", "npm")]
                self.assertEqual([e["name"] for e in calls], ["uv", "npm"])
                self.assertEqual(calls[0]["cwd"], str(self.workspace))
                self.assertIn("18123", calls[0]["args"])
                self.assertIn("127.0.0.1", calls[0]["args"])
                self.assertEqual(calls[1]["cwd"], str(self.root / "frontend"))
                self.assertEqual(calls[1]["backend_url"], "http://127.0.0.1:18123")
                self.assertEqual(calls[1]["args"], ["run", "dev", "--", "--port", "18124"])
                process.send_signal(signum)
                output = process.communicate(timeout=10)[0]
                self.assertEqual(process.returncode, 128 + signum, output)
                self.assert_children_stopped()

    def test_web_api_failure_timeout_and_frontend_failure_cleanup(self) -> None:
        for mode in ("api-exit", "api-timeout", "web-exit"):
            with self.subTest(mode=mode):
                self.log.unlink(missing_ok=True)
                self.env["FAKE_API_MODE"] = {"api-exit": "exit", "api-timeout": "hang"}.get(mode, "")
                self.env["FAKE_WEB_MODE"] = "exit" if mode == "web-exit" else ""
                process = self.launch_web("--timeout", "0.5" if mode == "api-timeout" else "3")
                output = process.communicate(timeout=10)[0]
                self.assertEqual(process.returncode, 1, output)
                if mode != "web-exit":
                    self.assertFalse(any(e["name"] == "npm" for e in self.events()))
                else:
                    self.assertTrue(any(e["name"] == "npm" for e in self.events()))
                    self.assertIn("状态码 7", output)
                self.assert_children_stopped()

    def test_web_rejects_invalid_settings_before_starting_children(self) -> None:
        for args in [("--api-port", "0"), ("--api-port", "3000"), ("--timeout", "nan")]:
            with self.subTest(args=args):
                result = self.run_script("start-web.sh", *args)
                self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.events(), [])

    @unittest.skipUnless(sockets_available(), "执行环境禁止本机 TCP socket；CI/普通开发环境运行此项")
    def test_real_health_probe_accepts_unconfigured_api_and_rejects_occupied_port(self) -> None:
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            port = occupied.getsockname()[1]
            result = self.run_script("start-web.sh", "--api-port", str(port))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("不可用", result.stderr)
            self.assertEqual(self.events(), [])
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0))
            api_port = free.getsockname()[1]
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0))
            web_port = free.getsockname()[1]
        self.env["FAKE_NETWORK"] = "1"
        process = self.launch_web("--api-port", str(api_port), "--port", str(web_port), network=True)
        self.wait_for_web(process)
        process.terminate()
        process.communicate(timeout=10)
        self.assert_children_stopped()


class HealthProbeTests(unittest.TestCase):
    def test_shutdown_waits_for_child_cleanup_after_leader_exit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="omt-shutdown-") as directory:
            root = Path(directory)
            ready, cleaned = root / "ready", root / "cleaned"
            worker = root / "worker.py"
            worker.write_text(
                "import signal,time\nfrom pathlib import Path\n"
                "def stop(signum,frame):\n"
                " time.sleep(0.15)\n"
                f" Path({str(cleaned)!r}).touch()\n"
                " raise SystemExit(0)\n"
                "signal.signal(signal.SIGTERM,stop)\n"
                f"Path({str(ready)!r}).touch()\n"
                "while True: time.sleep(0.05)\n"
            )
            leader = subprocess.Popen(
                [sys.executable, "-c",
                 "import subprocess,sys; subprocess.Popen([sys.executable,sys.argv[1]],"
                 "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)", str(worker)],
                start_new_session=True,
            )
            try:
                leader.wait(timeout=5)
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready.exists())
                run_web.stop_processes([leader])
                self.assertTrue(cleaned.exists(), "服务应有机会完成退出清理，不能因领进程先退出就立即强杀")
            finally:
                try:
                    os.killpg(leader.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_probe_checks_health_without_requiring_model_readiness(self) -> None:
        process = MagicMock()
        process.poll.return_value = None
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"status":"ok"}'
        connection = MagicMock()
        connection.getresponse.return_value.__enter__.return_value = response
        with patch.object(run_web, "HTTPConnection", return_value=connection):
            run_web.wait_for_api(process, "http://127.0.0.1:18123", 1)
        connection.request.assert_called_once_with("GET", "/health")
        connection.close.assert_called_once()

    def test_probe_detects_early_exit_and_timeout(self) -> None:
        process = MagicMock()
        process.poll.return_value = 9
        with self.assertRaisesRegex(RuntimeError, "退出"):
            run_web.wait_for_api(process, "http://127.0.0.1:18123", 1)
        process.poll.return_value = None
        with patch.object(run_web, "time") as clock:
            clock.monotonic.side_effect = [0, 2]
            with self.assertRaisesRegex(RuntimeError, "超时"):
                run_web.wait_for_api(process, "http://127.0.0.1:18123", 1)

    def test_occupied_port_is_rejected(self) -> None:
        with patch.object(run_web.socket, "socket") as factory:
            factory.return_value.__enter__.return_value.bind.side_effect = OSError("in use")
            with self.assertRaisesRegex(RuntimeError, "不可用"):
                run_web.available_port(18123)


if __name__ == "__main__":
    unittest.main()
