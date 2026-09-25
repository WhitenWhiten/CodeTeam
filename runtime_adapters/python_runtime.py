import asyncio
from runtime_adapters.runner import RuntimeBase

class PythonRuntime(RuntimeBase):
    def run_tests(self, repo_root, run_command):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_tests_async(repo_root, run_command))
        raise RuntimeError('Use await run_tests_async inside an event loop')
