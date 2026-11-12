import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from app.config import settings
from app.database import SessionLocal
from app.models import Submission, TestCase, UserProblem
from app.utils import utcnow

MAX_CODE_BYTES = 50_000

# 每一种语言：源文件名、编译命令（None 表示解释执行）、运行时解释器（可选）。
LANGUAGES = {
    "python": {"filename": "main.py", "compile": None, "interpreter": "python"},
    "python3": {"filename": "main.py", "compile": None, "interpreter": "python"},
    "javascript": {"filename": "main.js", "compile": None, "interpreter": "node"},
    "node": {"filename": "main.js", "compile": None, "interpreter": "node"},
    "c": {"filename": "main.c", "compile": ["gcc", "main.c", "-O2", "-std=c11", "-o", "main"]},
    "cpp": {"filename": "main.cpp", "compile": ["g++", "main.cpp", "-O2", "-std=c++17", "-o", "main"]},
    "c++": {"filename": "main.cpp", "compile": ["g++", "main.cpp", "-O2", "-std=c++17", "-o", "main"]},
}

IS_WINDOWS = os.name == "nt"


def normalize_output(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.replace("\r\n", "\n").replace("\r", "\n").splitlines()).rstrip("\n")


def _limits():
    """POSIX 下给子进程加资源限制；Windows 没有 resource 模块，直接跳过。"""
    if os.name != "posix":
        return
    try:
        import resource

        memory = settings.runner_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CPU, (settings.runner_timeout_seconds + 1, settings.runner_timeout_seconds + 1))
        resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    except (ImportError, OSError, ValueError):
        pass


def _popen_kwargs() -> dict:
    """跨平台的子进程创建参数。"""
    if IS_WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"start_new_session": True, "preexec_fn": _limits}


def _kill_process(proc) -> None:
    """结束子进程以及它派生的所有子进程（Windows 用 taskkill /T，POSIX 杀整个进程组）。"""
    if proc.poll() is not None:
        return
    if IS_WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def _which(command: str | None) -> str | None:
    """返回可执行文件的绝对路径；找不到时返回 None。"""
    if not command:
        return None
    return shutil.which(command)


def _resolve_runtime(spec: dict, source: Path, executable: Path) -> tuple[list[str] | None, str | None]:
    """把语言配置解析成实际命令行，同时检查依赖是否安装。返回 (命令行, 错误信息)。"""
    interpreter = spec.get("interpreter")
    if interpreter == "python":
        # 不要硬编码 "python3"：Windows 上装的是 python.exe / py，用当前解释器最稳。
        return [sys.executable, str(source)], None
    if interpreter == "node":
        node = _which("node")
        if not node:
            return None, "未找到 Node.js，请先安装 Node.js 并把它加入 PATH。"
        return [node, str(source)], None
    if not executable.exists():
        return None, "编译没有生成可执行文件。"
    return [str(executable)], None


def _decode_error(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return raw


def _execute(submission_id: int):
    db = SessionLocal()
    try:
        sub = db.get(Submission, submission_id)
        if not sub:
            return
        cases = db.query(TestCase).filter(TestCase.problem_id == sub.problem_id, TestCase.is_sample.is_(False)).order_by(TestCase.id).all()
        if not cases:
            cases = db.query(TestCase).filter(TestCase.problem_id == sub.problem_id).order_by(TestCase.id).all()
        sub.total_cases = len(cases)
        if not cases:
            sub.status, sub.error_message = "Compile Error", "题目还没有配置判题用例"
            sub.finished_at = utcnow()
            db.commit()
            return
        lang = sub.language.lower()
        spec = LANGUAGES.get(lang)
        if not spec:
            sub.status, sub.error_message = "Compile Error", "不支持的语言。可用：Python、JavaScript、C、C++"
            sub.finished_at = utcnow()
            db.commit()
            return

        root = Path(tempfile.mkdtemp(prefix=f"submission-{submission_id}-"))
        try:
            source = root / spec["filename"]
            source.write_text(sub.code, encoding="utf-8")
            # MinGW 在 Windows 上生成的是 main.exe，Linux 上是 main。
            executable = root / ("main.exe" if IS_WINDOWS else "main")

            compile_cmd = spec.get("compile")
            if compile_cmd:
                compiler = _which(compile_cmd[0])
                if not compiler:
                    sub.status, sub.error_message = "Compile Error", f"未找到编译器 {compile_cmd[0]}，请先安装并把它加入 PATH。"
                    sub.finished_at = utcnow()
                    db.commit()
                    return
                try:
                    built = subprocess.run(
                        [compiler, *compile_cmd[1:]],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=15,
                        **_popen_kwargs(),
                    )
                except subprocess.TimeoutExpired:
                    sub.status, sub.error_message = "Compile Error", "编译超时"
                    sub.finished_at = utcnow()
                    db.commit()
                    return
                if built.returncode:
                    sub.status, sub.error_message = "Compile Error", _decode_error(built.stderr)[-4000:]
                    sub.finished_at = utcnow()
                    db.commit()
                    return

            runtime, runtime_error = _resolve_runtime(spec, source, executable)
            if runtime_error:
                sub.status, sub.error_message = "Compile Error", runtime_error
                sub.finished_at = utcnow()
                db.commit()
                return

            run_env = os.environ.copy()
            run_env.setdefault("PYTHONIOENCODING", "utf-8")
            run_env.setdefault("PYTHONUTF8", "1")

            started, passed, max_runtime, error = time.perf_counter(), 0, 0, None
            sub.status = "Accepted"
            for case in cases:
                try:
                    case_started = time.perf_counter()
                    proc = subprocess.Popen(
                        runtime,
                        cwd=root,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        env=run_env,
                        **_popen_kwargs(),
                    )
                    try:
                        stdout, stderr = proc.communicate(case.input_data, timeout=settings.runner_timeout_seconds)
                        result = subprocess.CompletedProcess(runtime, proc.returncode, stdout, stderr)
                    except subprocess.TimeoutExpired:
                        _kill_process(proc)
                        proc.communicate()
                        raise
                except subprocess.TimeoutExpired:
                    sub.status, error = "Time Limit Exceeded", f"用例 {passed + 1} 执行超时"
                    break
                max_runtime = max(max_runtime, int((time.perf_counter() - case_started) * 1000))
                if result.returncode:
                    sub.status, error = "Runtime Error", (_decode_error(result.stderr) or f"进程退出码 {result.returncode}")[-4000:]
                    break
                if normalize_output(result.stdout or "") != normalize_output(case.expected_output or ""):
                    sub.status = "Wrong Answer"
                    break
                passed += 1
            sub.passed_cases, sub.runtime_ms = passed, max(max_runtime, int((time.perf_counter() - started) * 1000))
            sub.error_message = error
        except Exception as exc:
            sub.status, sub.error_message = "Runtime Error", str(exc)[:4000]
        finally:
            shutil.rmtree(root, ignore_errors=True)
        sub.finished_at = utcnow()
        progress = db.query(UserProblem).filter_by(user_id=sub.user_id, problem_id=sub.problem_id).first()
        if not progress:
            progress = UserProblem(user_id=sub.user_id, problem_id=sub.problem_id)
            db.add(progress)
        progress.attempted, progress.last_submission_at = True, sub.finished_at
        if sub.status == "Accepted" and not progress.solved:
            progress.solved, progress.first_solved_at = True, sub.finished_at
        db.commit()
    finally:
        db.close()
