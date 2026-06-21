# core/repo_manager.py
from typing import Set, Dict, Optional, Iterable, Any
import os
import json
import re
import subprocess
import shutil
import threading
from contextlib import contextmanager

class RepoManager:
    def __init__(
        self,
        root: str,
        allowed_files_all: Set[str],
        allowed_files_by_agent: Dict[str, Set[str]],
        git_enabled: bool = True,
    ):
        self.root = root
        self.allowed_files_all = allowed_files_all
        self.allowed_files_by_agent = allowed_files_by_agent
        self.git_enabled = git_enabled
        self._collaboration_lock = threading.RLock()

    @contextmanager
    def collaboration_lock(self):
        with self._collaboration_lock:
            yield

    def _relpath(self, path: str) -> str:
        # Normalize to a path relative to the repository root.
        rel = os.path.relpath(path, self.root) if os.path.isabs(path) else path
        return rel.replace("\\", "/")

    def _assert_allowed(self, rel_path: str, agent_id: Optional[str] = None):
        norm = rel_path.replace("\\", "/")

        # Global permissions expanded from SDS repo_structure.
        if norm in self.allowed_files_all:
            return

        # Per-agent exact file permissions.
        if agent_id:
            agent_set = self.allowed_files_by_agent.get(agent_id, set())
            if norm in agent_set:
                return

        # QA may write any file under tests/ without each file being declared in the SDS.
        if agent_id == "QA" and (norm == "tests" or norm.startswith("tests/")):
            return

        raise PermissionError(f"Write denied: {norm} not declared in SDS repo_structure")

    # Read/write API; writes are permission-checked.
    def write_file(self, path: str, content: str, agent_id: Optional[str] = None):
        rel = self._relpath(path)
        self._assert_allowed(rel, agent_id)
        abspath = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        with open(abspath, "w", encoding="utf-8") as f:
            f.write(content)

    def append_file(self, path: str, content: str, agent_id: Optional[str] = None):
        rel = self._relpath(path)
        self._assert_allowed(rel, agent_id)
        abspath = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        with open(abspath, "a", encoding="utf-8") as f:
            f.write(content)

    def write_json(self, path: str, obj, agent_id: Optional[str] = None):
        rel = self._relpath(path)
        self._assert_allowed(rel, agent_id)
        abspath = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(abspath), exist_ok=True)
        with open(abspath, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

    # Reads and existence checks are unrestricted.
    def exists(self, path: str) -> bool:
        rel = self._relpath(path)
        abspath = os.path.join(self.root, rel)
        return os.path.exists(abspath)

    def is_file(self, path: str) -> bool:
        rel = self._relpath(path)
        abspath = os.path.join(self.root, rel)
        return os.path.isfile(abspath)

    def is_dir(self, path: str) -> bool:
        rel = self._relpath(path)
        abspath = os.path.join(self.root, rel)
        return os.path.isdir(abspath)

    def read_file(self, path: str, encoding: str = "utf-8") -> str:
        rel = self._relpath(path)
        abspath = os.path.join(self.root, rel)
        with open(abspath, "r", encoding=encoding) as f:
            return f.read()

    def read_bytes(self, path: str) -> bytes:
        rel = self._relpath(path)
        abspath = os.path.join(self.root, rel)
        with open(abspath, "rb") as f:
            return f.read()

    def read_json(self, path: str):
        rel = self._relpath(path)
        abspath = os.path.join(self.root, rel)
        with open(abspath, "r", encoding="utf-8") as f:
            return json.load(f)

    # Git support.
    def _is_git_repo(self) -> bool:
        if not self.git_enabled:
            return False
        return os.path.isdir(os.path.join(self.root, ".git"))

    def _ensure_git_allowed(self, operation: str = "git operation"):
        if not self.git_enabled:
            raise PermissionError(f"Git collaboration disabled: {operation} is not allowed")

    def _git(self, *args, check=True) -> subprocess.CompletedProcess:
        self._ensure_git_allowed("git command execution")
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=check,
        )

    def _current_branch(self) -> Optional[str]:
        if not self.git_enabled or shutil.which("git") is None or not self._is_git_repo():
            return None
        res = self._git("branch", "--show-current", check=False)
        branch = (res.stdout or "").strip()
        return branch or None

    def _agent_branch_name(self, agent_id: Optional[str]) -> str:
        raw = agent_id or "agent"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-._")
        return f"agent/{safe or 'agent'}"

    def _default_branch(self) -> str:
        return "main"

    def ensure_agent_branch(self, agent_id: Optional[str]) -> Optional[str]:
        """
        Ensure a lightweight branch exists for an agent and check it out.
        Returns the branch name, or None when git collaboration is unavailable.
        """
        if not self.git_enabled:
            return None
        if shutil.which("git") is None:
            return None

        self._ensure_git()
        self.ensure_integration_branch()
        branch = self._agent_branch_name(agent_id)
        if self._current_branch() == branch:
            return branch

        exists = self._git("rev-parse", "--verify", branch, check=False)
        try:
            if exists.returncode == 0:
                ret = self._git("checkout", branch, check=False)
            else:
                ret = self._git("checkout", "-b", branch, check=False)
            return branch if ret.returncode == 0 else None
        except subprocess.CalledProcessError:
            return None

    def checkout_agent_branch(self, agent_id: Optional[str]) -> Optional[str]:
        return self.ensure_agent_branch(agent_id)

    def ensure_integration_branch(self) -> Optional[str]:
        if not self.git_enabled:
            return None
        if shutil.which("git") is None:
            return None

        self._ensure_git()
        branch = self._default_branch()
        current = self._current_branch()
        if current == branch:
            return branch

        exists = self._git("rev-parse", "--verify", branch, check=False)
        if exists.returncode == 0:
            ret = self._git("checkout", branch, check=False)
            return branch if ret.returncode == 0 else current

        if current:
            create = self._git("branch", branch, check=False)
            if create.returncode == 0:
                ret = self._git("checkout", branch, check=False)
                return branch if ret.returncode == 0 else current

        ret = self._git("checkout", "-b", branch, check=False)
        return branch if ret.returncode == 0 else current

    def integrate_agent_branch(self, agent_id: Optional[str]) -> bool:
        if not self.git_enabled:
            return False
        if shutil.which("git") is None:
            return False
        if not self._is_git_repo():
            return False

        source_branch = self._agent_branch_name(agent_id)
        source_exists = self._git("rev-parse", "--verify", source_branch, check=False)
        if source_exists.returncode != 0:
            return False

        integration = self.ensure_integration_branch()
        if not integration:
            return False

        merge = self._git(
            "merge",
            "--no-ff",
            "--no-edit",
            "-X",
            "theirs",
            source_branch,
            check=False,
        )
        return merge.returncode == 0

    def cleanup_runtime_artifacts(self) -> None:
        root = os.path.abspath(self.root)
        for dirpath, dirnames, filenames in os.walk(root, topdown=False):
            base = os.path.basename(dirpath)
            if base == ".git":
                dirnames[:] = []
                continue
            for filename in filenames:
                if filename.endswith(".pyc"):
                    try:
                        os.remove(os.path.join(dirpath, filename))
                    except OSError:
                        pass
            if base == "__pycache__":
                try:
                    shutil.rmtree(dirpath)
                except OSError:
                    pass

    def finalize_output_repository(self) -> None:
        self.cleanup_runtime_artifacts()
        if not self.git_enabled or shutil.which("git") is None:
            return
        self.ensure_integration_branch()
        self.commit_all("chore: finalize generated repository")

    def _ensure_git(self, author_name: Optional[str] = None, author_email: Optional[str] = None):
        if not self.git_enabled:
            return
        if shutil.which("git") is None:
            return

        if not self._is_git_repo():
            self._git("init")

        # Set local identity if it is not already configured.
        try:
            self._git("config", "user.name")
        except subprocess.CalledProcessError:
            self._git("config", "user.name", author_name or "RepoManager")

        try:
            self._git("config", "user.email")
        except subprocess.CalledProcessError:
            self._git("config", "user.email", author_email or "repo@example.local")

    def commit_all(self, message: str, author_name: Optional[str] = None, author_email: Optional[str] = None) -> Optional[str]:
        """
        Stage and commit all changes in the repo root.
        Returns the commit hash, or None if git is not available.
        """
        if not self.git_enabled:
            return None
        if shutil.which("git") is None:
            return None

        self._ensure_git(author_name, author_email)
        self._git("add", "-A")

        env = os.environ.copy()
        if author_name:
            env["GIT_AUTHOR_NAME"] = author_name
            env["GIT_COMMITTER_NAME"] = author_name
        if author_email:
            env["GIT_AUTHOR_EMAIL"] = author_email
            env["GIT_COMMITTER_EMAIL"] = author_email

        subprocess.run(
            ["git", "commit", "-m", message, "--allow-empty", "--no-verify"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )

        try:
            res = self._git("rev-parse", "HEAD")
            return res.stdout.strip()
        except subprocess.CalledProcessError:
            return None

    # Initialize structure from list/dict/RepoNode-like inputs.
    def init_structure(self, structure: Any):
        """
        Initialize repository directories and files without permission checks.
        Supported shapes:
          1) Sequence (list/tuple/set), where each item may be:
             - A relative path string ('src/app.py' or 'tests/')
             - A RepoNode-like object with attributes such as name/path, children/type/is_dir/content
             - A dictionary; see shape 2
          2) A dictionary tree: { "src": {"app.py": None, "pkg": {"__init__.py": None}}, "tests": {} }
             Leaf keys whose values are None or strings are treated as files; string values become initial content.
          3) A single RepoNode-like object used as the root node.
        """
        os.makedirs(self.root, exist_ok=True)

        def _touch_file(abs_path: str, content: Optional[str] = None):
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write("" if content is None else str(content))

        def _get(obj: Any, names: list[str], default=None):
            for n in names:
                if isinstance(obj, dict) and n in obj:
                    return obj[n]
                if hasattr(obj, n):
                    return getattr(obj, n)
            return default

        def _looks_like_reponode(obj: Any) -> bool:
            # Rough detection by common RepoNode attributes.
            return any(hasattr(obj, a) for a in ("name", "path", "children", "is_dir", "type", "node_type"))

        def _init_from_iter(items: Iterable[Any]):
            for item in items:
                # String path.
                if isinstance(item, str):
                    p_norm = item.replace("\\", "/")
                    abs_path = os.path.join(self.root, p_norm)
                    if p_norm.endswith("/"):
                        os.makedirs(abs_path, exist_ok=True)
                        continue
                    name = os.path.basename(p_norm)
                    if "." in name:
                        _touch_file(abs_path, "")
                    else:
                        os.makedirs(abs_path, exist_ok=True)
                    continue

                # Dictionary tree node.
                if isinstance(item, dict):
                    _init_from_tree(self.root, item)
                    continue

                # RepoNode-like object.
                if _looks_like_reponode(item):
                    _init_from_reponode(item, self.root)
                    continue

                raise TypeError(f"Unsupported repo_structure item type: {type(item)}")

        def _init_from_tree(base_abs: str, node: Any):
            if isinstance(node, dict):
                for name, child in node.items():
                    child_abs = os.path.join(base_abs, name)
                    if isinstance(child, dict):
                        os.makedirs(child_abs, exist_ok=True)
                        _init_from_tree(child_abs, child)
                    else:
                        # None/string/other child values are files; strings are initial content.
                        _touch_file(child_abs, child if isinstance(child, str) else None)
            else:
                raise TypeError("repo_structure dict must map names to dict (dir) or None/str (file content)")

        def _init_children_for_dir(dir_abs: str, children: Any):
            # children may be a list/tuple/set or a dict.
            if children is None:
                return
            if isinstance(children, (list, tuple, set)):
                for ch in children:
                    if isinstance(ch, str):
                        # Child path relative to dir_abs.
                        p_norm = ch.replace("\\", "/")
                        abs_path = os.path.join(dir_abs, p_norm)
                        if p_norm.endswith("/"):
                            os.makedirs(abs_path, exist_ok=True)
                        else:
                            name = os.path.basename(p_norm)
                            if "." in name:
                                _touch_file(abs_path, "")
                            else:
                                os.makedirs(abs_path, exist_ok=True)
                    elif isinstance(ch, dict):
                        # Treat this dict as a subtree attached to the current directory.
                        _init_from_tree(dir_abs, ch)
                    elif _looks_like_reponode(ch):
                        _init_from_reponode(ch, dir_abs)
                    else:
                        raise TypeError(f"Unsupported child type in children list: {type(ch)}")
            elif isinstance(children, dict):
                _init_from_tree(dir_abs, children)
            else:
                raise TypeError(f"Unsupported children container type: {type(children)}")

        def _init_from_reponode(node: Any, parent_abs: str):
            # Resolve path/name.
            path_attr = _get(node, ["path", "relpath", "relative_path"], None)
            name_attr = _get(node, ["name", "basename"], None)

            # Compute absolute path: prefer name joined to the parent; otherwise use path relative to root.
            if name_attr:
                abs_path = os.path.join(parent_abs, str(name_attr))
            elif isinstance(path_attr, str) and path_attr:
                # RepoNode.path in nested trees is relative to the current parent node.
                abs_path = os.path.join(parent_abs, path_attr.replace("\\", "/"))
            else:
                raise ValueError("RepoNode must have either 'name' or 'path'")

            # Determine directory or file.
            is_dir = _get(node, ["is_dir"], None)
            if is_dir is None:
                node_type = _get(node, ["type", "node_type", "kind"], None)
                if isinstance(node_type, str):
                    lt = node_type.lower()
                    if lt in ("dir", "directory", "folder"):
                        is_dir = True
                    elif lt in ("file",):
                        is_dir = False
                if is_dir is None:
                    # Fall back to detecting whether children exist.
                    is_dir = _get(node, ["children", "nodes", "items", "entries"], None) is not None

            if is_dir:
                os.makedirs(abs_path, exist_ok=True)
                children = _get(node, ["children", "nodes", "items", "entries"], None)
                _init_children_for_dir(abs_path, children)
            else:
                content = _get(node, ["content", "text", "initial_content", "body"], None)
                _touch_file(abs_path, content if isinstance(content, (str, bytes)) else None)

        # Entry dispatch.
        if isinstance(structure, (list, tuple, set)):
            _init_from_iter(structure)
        elif isinstance(structure, dict):
            _init_from_tree(self.root, structure)
        elif _looks_like_reponode(structure):
            _init_from_reponode(structure, self.root)
        else:
            raise TypeError("repo_structure must be a list/tuple/set of paths or a nested dict tree or a RepoNode-like object")

    def _symbol_names(self, symbols: Any) -> list[str]:
        if not isinstance(symbols, list):
            return []
        names = []
        for item in symbols:
            if isinstance(item, dict):
                name = item.get("name") or item.get("signature")
            else:
                name = getattr(item, "name", None) or getattr(item, "signature", None)
            if name:
                names.append(str(name))
        return names

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [self._json_safe(item) for item in value]
        if isinstance(value, set):
            return sorted(self._json_safe(item) for item in value)
        if hasattr(value, "__dict__"):
            return self._json_safe(vars(value))
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _normalize_update_reason(self, rel_path: str, update_record: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        record = dict(update_record or {})
        change_type = record.get("change_type") or "update"
        modified_exported_symbols = record.get("modified_exported_symbols")
        if modified_exported_symbols is None:
            modified_exported_symbols = []
            for key in (
                "functions_added",
                "functions_modified",
                "functions_removed",
                "classes_added",
                "classes_modified",
                "classes_removed",
            ):
                modified_exported_symbols.extend(self._symbol_names(record.get(key, [])))
        seen = set()
        modified_exported_symbols = [
            s for s in modified_exported_symbols
            if isinstance(s, str) and s and not (s in seen or seen.add(s))
        ]

        affected_dependent_files = record.get("affected_dependent_files")
        if affected_dependent_files is None:
            affected_dependent_files = record.get("dependent_files_affected", [])
        if not isinstance(affected_dependent_files, list):
            affected_dependent_files = []

        compatibility_note = record.get("compatibility_note")
        if not compatibility_note:
            compatibility_note = "No compatibility impact recorded."

        normalized = {
            "target_file": record.get("target_file") or record.get("file_path") or rel_path,
            "file_path": record.get("file_path") or record.get("target_file") or rel_path,
            "change_type": change_type,
            "functions_added": record.get("functions_added", []),
            "functions_modified": record.get("functions_modified", []),
            "functions_removed": record.get("functions_removed", []),
            "classes_added": record.get("classes_added", []),
            "classes_modified": record.get("classes_modified", []),
            "classes_removed": record.get("classes_removed", []),
            "modified_exported_symbols": modified_exported_symbols,
            "compatibility_note": str(compatibility_note),
            "affected_dependent_files": affected_dependent_files,
            "rationale": record.get("rationale", ""),
            "related_files_brief_used": record.get("related_files_brief_used", []),
        }
        return self._json_safe(normalized)

    def _build_commit_message(
        self,
        rel_path: str,
        update_record: Optional[Dict[str, Any]],
        agent_id: Optional[str],
        message: Optional[str],
    ) -> str:
        normalized_reason = self._normalize_update_reason(rel_path, update_record)
        action = normalized_reason.get("change_type") or "update"
        summary = message or f"{agent_id or 'agent'}: {action} {rel_path}"
        reason_json = json.dumps(normalized_reason, ensure_ascii=False, sort_keys=True)
        return f"{summary}\n\nupdate_reason: {reason_json}"
        
    def commit_file(
        self,
        path: str,
        update_record: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        message: Optional[str] = None,
        author_name: Optional[str] = None,
        author_email: Optional[str] = None,
    ) -> Optional[str]:
        """
        Commit changes for a single file only.
        - update_record: optional record used to extract change_type into the commit message.
        - Returns the commit hash; returns None when git is unavailable or there are no changes.
        - Skips empty commits and avoids raising for them.
        """
        if not self.git_enabled:
            return None
        if shutil.which("git") is None:
            return None

        rel = self._relpath(path)
        self._ensure_git(author_name, author_email)

        # Build the commit message.
        msg = self._build_commit_message(rel, update_record, agent_id, message)

        # Stage only this file; if it does not exist or cannot be staged, return None.
        try:
            self._git("add", rel)
        except subprocess.CalledProcessError:
            return None

        # Check this file for staged changes to avoid reading other workers' staged files.
        diff = self._git("diff", "--cached", "--name-only", "--", rel, check=False)
        if not (diff.stdout or "").strip():
            return None

        env = os.environ.copy()
        if author_name:
            env["GIT_AUTHOR_NAME"] = author_name
            env["GIT_COMMITTER_NAME"] = author_name
        if author_email:
            env["GIT_AUTHOR_EMAIL"] = author_email
            env["GIT_COMMITTER_EMAIL"] = author_email

        # Commit without check=True; return None if the commit fails.
        ret = subprocess.run(
            ["git", "commit", "-m", msg, "--no-verify", "--only", "--", rel],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        if ret.returncode != 0:
            # Common causes: empty commit or hook failure despite --no-verify.
            return None

        # Return current HEAD.
        res = self._git("rev-parse", "HEAD", check=False)
        commit_hash = res.stdout.strip() if res.returncode == 0 else None
        if commit_hash and agent_id:
            self.integrate_agent_branch(agent_id)
        return commit_hash
