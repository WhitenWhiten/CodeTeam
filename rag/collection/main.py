import os
import json
import time
import base64
import requests

# 配置参数：请按需修改
MIN_STARS = 1000        # 仅获取超过这个星标数量的仓库
MAX_REPOS = 500          # 最大处理的仓库数量（用于控制脚本运行时间）
PER_PAGE = 100            # GitHub API 搜索每页条数
COMMITS_PER_REPO = 30     # 每个仓库抓取的最近提交数量

GITHUB_API = "https://api.github.com"

def get_headers(token=None):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    return headers

def handle_rate_limit(resp):
    reset = resp.headers.get("X-RateLimit-Reset")
    if reset:
        reset_ts = int(reset)
        sleep_sec = max(0, reset_ts - int(time.time()) + 5)
        print(f"[RateLimit] 触发速率限制，休眠 {sleep_sec} 秒...")
        time.sleep(sleep_sec)
    else:
        # 默认短暂休眠以避免连锁失败
        time.sleep(60)

def get_repos(min_stars, session, max_results=MAX_REPOS):
    repos = []
    page = 1
    while len(repos) < max_results:
        params = {
            "q": f"stars:>{min_stars}",
            "sort": "stars",
            "order": "desc",
            "per_page": PER_PAGE,
            "page": page
        }
        resp = session.get(f"{GITHUB_API}/search/repositories", params=params)
        if resp.status_code == 403:
            handle_rate_limit(resp)
            continue
        if not resp.ok:
            print(f"Error: 读取仓库列表失败，状态码 {resp.status_code}，信息: {resp.text}")
            break
        data = resp.json()
        items = data.get("items", [])
        if not items:
            break
        for it in items:
            repos.append(it)
            if len(repos) >= max_results:
                break
        page += 1
    return repos

def fetch_readme(owner, repo, session):
    url = f"{GITHUB_API}/repos/{owner}/{repo}/readme"
    r = session.get(url)
    if not r.ok:
        return ""
    data = r.json()
    content = data.get("content", "")
    encoding = data.get("encoding", "base64")
    if encoding == "base64":
        try:
            decoded = base64.b64decode(content).decode("utf-8", errors="ignore")
            return decoded
        except Exception:
            return ""
    else:
        return content

def fetch_default_branch(owner, repo, session):
    url = f"{GITHUB_API}/repos/{owner}/{repo}"
    r = session.get(url)
    if not r.ok:
        raise Exception(f"Failed to fetch repo {owner}/{repo}")
    data = r.json()
    return data.get("default_branch", "master")

def fetch_tree(owner, repo, branch, session):
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    r = session.get(url)
    if not r.ok:
        raise Exception(f"Failed to fetch tree for {owner}/{repo}")
    data = r.json()
    tree = data.get("tree", [])
    return tree

def build_nested_tree(entries):
    # 将路径列表转换为嵌套的字典结构
    root = {}
    for e in entries:
        path = e.get("path")
        if not path:
            continue
        parts = path.split("/")
        current = root
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                # 最后一层，标记为文件
                current[part] = None
            else:
                if part not in current or current[part] is None:
                    current[part] = {}
                current = current[part]
    return root

def stringify_node(name, node_dict):
    # 将一个目录节点转换成 "name[contents...]" 的表达
    contents = []
    for child in sorted(node_dict.keys()):
        child_node = node_dict[child]
        if child_node is None:
            contents.append(child)  # 文件名直接作为字符串
        else:
            contents.append(stringify_node(child, child_node))
    return f"{name}[" + ", ".join(contents) + "]"

def stringify_root(root_dict):
    # 将根目录的内容转换成 "[...]" 表达式
    elements = []
    for name in sorted(root_dict.keys()):
        node = root_dict[name]
        if node is None:
            elements.append(name)
        else:
            elements.append(stringify_node(name, node))
    return "[" + ", ".join(elements) + "]"

def fetch_commits(owner, repo, branch, session, max_commits=30):
    url = f"{GITHUB_API}/repos/{owner}/{repo}/commits"
    params = {"sha": branch, "per_page": max_commits}
    r = session.get(url, params=params)
    if not r.ok:
        print(f"Warning: 读取提交历史失败 {owner}/{repo}，状态 {r.status_code}")
        return []
    data = r.json()
    commits = []
    for c in data:
        sha = c.get("sha")
        commit_info = c.get("commit", {}) or {}
        author_info = commit_info.get("author", {}) or {}
        author_name = author_info.get("name")
        date = author_info.get("date")
        message = commit_info.get("message")
        commits.append({"sha": sha, "author": author_name, "date": date, "message": message})
    return commits

def main():
    token = "Github token here"
    session = requests.Session()
    session.headers.update(get_headers(token))

    print(f"开始检索星标数大于 {MIN_STARS} 的仓库...")
    repos = get_repos(MIN_STARS, session, max_results=MAX_REPOS)

    results = []
    for item in repos:
        full_name = item.get("full_name")
        if not full_name:
            continue
        owner, repo = full_name.split("/", 1)
        print(f"处理: {full_name} ...")
        try:
            readme_text = fetch_readme(owner, repo, session)
            default_branch = fetch_default_branch(owner, repo, session)
            tree_entries = fetch_tree(owner, repo, default_branch, session)
            nested = build_nested_tree(tree_entries)
            tree_string = stringify_root(nested)

            commits = fetch_commits(owner, repo, default_branch, session, max_commits=COMMITS_PER_REPO)

            results.append({
                "full_name": full_name,
                "readme": readme_text,
                "tree": tree_string,
                "commits": commits
            })
        except Exception as e:
            print(f"错误: 在处理 {full_name} 时出现异常: {e}")

    with open("github_repos.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"完成。已将数据写入 github_repos.json，共 {len(results)} 个仓库。")

if __name__ == "__main__":
    main()
