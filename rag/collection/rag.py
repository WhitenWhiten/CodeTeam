import os
import hashlib
import numpy as np
from sentence_transformers import SentenceTransformer
import json

# load context source
with open("./github_repos.json", mode='r', encoding='utf-8') as f:
    repos = json.load(f)
source_context = []
reversed_source_context = {}
for repo in repos:
    source_context.append(repo["readme"])
    reversed_source_context[repo["readme"]] = repo
    
   

def compute_cache_path(texts, cache_dir="cache", prefix="corpus_embeddings"):
    # 基于语料内容生成短哈希，保证语料变动时生成新的缓存文件
    os.makedirs(cache_dir, exist_ok=True)
    hasher = hashlib.sha256()
    # 连接时使用不可混淆的分隔符，避免拼接歧义
    for t in texts:
        hasher.update(t.encode("utf-8"))
        hasher.update(b"\x1f")  # unit separator
    short_hash = hasher.hexdigest()[:16]
    return os.path.join(cache_dir, f"{prefix}_{short_hash}.npy")

def compute_or_load_embeddings(model, texts, cache_dir="cache", prefix="corpus_embeddings", batch_size=64):
    emb_path = compute_cache_path(texts, cache_dir=cache_dir, prefix=prefix)
    if os.path.exists(emb_path):
        emb = np.load(emb_path)
        if emb.shape[0] == len(texts):
            print(f"加载缓存向量：{emb_path}")
            return emb
        else:
            print("检测到缓存向量条目数与语料不匹配，重新计算向量。")

    print("开始编码语料（可能需要一些时间，取决于语料大小与 CPU 性能）...")
    embeddings = model.encode(texts, convert_to_numpy=True, batch_size=batch_size, show_progress_bar=True)
    np.save(emb_path, embeddings)
    print(f"已将语料向量保存到 {emb_path}")
    return embeddings

def l2_normalize(x, axis=1, eps=1e-10):
    if x.ndim == 1:
        norm = np.linalg.norm(x) + eps
        return x / norm
    norm = np.linalg.norm(x, axis=axis, keepdims=True) + eps
    return x / norm

def top_k_similar(corpus_texts, corpus_emb, query, model, top_x=5):
    # 编码 query
    q_emb = model.encode([query], convert_to_numpy=True)[0]
    corpus_emb_norm = l2_normalize(corpus_emb, axis=1)
    q_emb_norm = l2_normalize(q_emb, axis=0)
    sims = np.dot(corpus_emb_norm, q_emb_norm)  # shape (n,)
    top_x = min(top_x, len(sims))
    idx = np.argsort(-sims)[:top_x]
    results = [(int(i), corpus_texts[i], float(sims[i])) for i in idx]
    return results


def query(Q, top=5, model_name="all-MiniLM-L6-v2"):
    model = SentenceTransformer(model_name)
    corpus_emb = compute_or_load_embeddings(model, source_context, cache_dir="cache", prefix="corpus_embeddings", batch_size=64)
    results = top_k_similar(source_context, corpus_emb, Q, model, top_x=top)

    ret = []
    for rank, (i, text, score) in enumerate(results, start=1):
        ret.append([rank, reversed_source_context[text], score])
    return ret


def main():
    result = query("build a personal website with vue.")
    for r in result:
        print(r[1]["full_name"])
    

if __name__ == "__main__":
    main()
