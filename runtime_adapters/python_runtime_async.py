from runtime_adapters.runner import RuntimeBase

class PythonRuntimeAsync(RuntimeBase):
    async def run_tests(self, repo_root, run_command):
        return await self.run_tests_async(repo_root, run_command)
