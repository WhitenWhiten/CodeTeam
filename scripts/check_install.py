"""Build and execute the installed wheel outside the checkout without network."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def run(args, cwd, env):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def main():
    repository = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PIP_NO_INDEX="1")
    for name in list(env):
        if name.startswith("CODETEAM_") or name == "OPENAI_BASE_URL":
            env.pop(name)
    with tempfile.TemporaryDirectory(prefix="codeteam-install-") as directory:
        root = Path(directory)
        wheel_dir, target = root / "wheels", root / "installed"
        run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", str(wheel_dir), str(repository)], root, env)
        wheel = next(wheel_dir.glob("*.whl"))
        run([sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), str(wheel)], root, env)
        env["PYTHONPATH"] = str(target)
        probe = "import app,json; from pathlib import Path; from importlib.metadata import version; print(json.dumps({'module':app.__file__, 'version':version('codeteam-runtime'), 'prompts':len(list((Path(app.__file__).parent.parent/'prompts').glob('*.md')))}))"
        installed = json.loads(run([sys.executable, "-c", probe], root, env))
        assert Path(installed["module"]).is_relative_to(target)
        assert installed["prompts"] == 4
        launchers = list(target.rglob("codeteam.exe" if os.name == "nt" else "codeteam"))
        if len(launchers) != 1:
            raise RuntimeError(f"Expected one installed console launcher, found: {launchers}")
        executable = launchers[0]
        for command in ('codeteam-experiment', 'codeteam-sft'):
            launcher = next(target.rglob(command + ('.exe' if os.name == 'nt' else '')))
            assert 'usage:' in run([str(launcher), '--help'], root, env)
        result = json.loads(run([str(executable), "--provider", "mock", "--no-git", "--architects", "1", "--workspace", str(root / "work")], root, env))
        assert result["status"] == "success" and result["qa"]["counts"]["passed"] == 4
        print(json.dumps({"wheel": wheel.name, "installed_version": installed["version"], "packaged_prompts": installed["prompts"], "cli_status": result["status"], "passed": 4}))


if __name__ == "__main__":
    main()
