"""Cancellable subprocess execution with child-tree cleanup."""
import asyncio
import os
import signal
import subprocess


async def _terminate_tree(proc):
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(proc.pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await killer.wait()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    await proc.wait()


async def run_process(argv, cwd, timeout=120, env=None):
    kwargs = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
              else {"start_new_session": True})
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=str(cwd), env=env, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, **kwargs)
    reader = asyncio.create_task(proc.communicate())
    try:
        out, _ = await asyncio.wait_for(asyncio.shield(reader), timeout)
        return {"returncode": proc.returncode, "output": out.decode("utf-8", errors="replace"),
                "timed_out": False, "pid": proc.pid}
    except (TimeoutError, asyncio.CancelledError) as exc:
        await _terminate_tree(proc)
        try:
            out, _ = await asyncio.wait_for(reader, 5)
        except (TimeoutError, asyncio.CancelledError):
            out = b""
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        if isinstance(exc, asyncio.CancelledError):
            raise
        return {"returncode": proc.returncode, "output": out.decode("utf-8", errors="replace"),
                "timed_out": True, "pid": proc.pid}
