"""
analyze_experiment_results.py
==============================
Read task-level raw data from experiment_results.xlsx and
generate all paper tables + inline body-text statistics.

Output:
  - Console: human-readable formatted tables
  - statistics_report.json: machine-readable JSON

Usage: python analyze_experiment_results.py
Dependencies: pip install numpy pandas openpyxl scipy
"""

import json, sys
import numpy as np
import pandas as pd
from scipy import stats as sp_stats

XLSX = "experiment_results.xlsx"
JSON_OUT = "statistics_report.json"

report = {}  # final output JSON


def fmt(val, prec=1):
    """Format a numeric value to given precision."""
    return round(float(val), prec)


def mean_std_str(arr, prec=1):
    """Return a 'mean±std' string."""
    m = np.mean(arr)
    s = np.std(arr, ddof=0)
    return f"{m:.{prec}f}±{s:.{prec}f}"


def print_header(title):
    w = 80
    print()
    print("=" * w)
    print(f"  {title}")
    print("=" * w)


# ═══════════════════════════════════════════════════════════
#  Load data
# ═══════════════════════════════════════════════════════════
print(f"Reading {XLSX} ...")
xls = pd.ExcelFile(XLSX)
df_sketch   = pd.read_excel(xls, "SketchEval_main")
df_decomp   = pd.read_excel(xls, "SketchBLEU_decomp")
df_nl2repo  = pd.read_excel(xls, "NL2RepoBench_main")
df_errors   = pd.read_excel(xls, "NL2RepoBench_errors")
df_ablation = pd.read_excel(xls, "Ablation_SketchEval")
df_planning = pd.read_excel(xls, "Planning_diagnostics")
df_eff      = pd.read_excel(xls, "Efficiency_diagnostics")
df_qa       = pd.read_excel(xls, "QA_convergence")
print("Done.\n")

DIFF_ORDER = ["easy", "medium", "hard"]


# ═══════════════════════════════════════════════════════════
#  Table 1: SketchEval main (tab:rq1-main)
# ═══════════════════════════════════════════════════════════
print_header("Table 1: SketchEval Performance (tab:rq1-main)")

METHOD_ORDER_PE  = ["Vanilla", "ChatDev", "AutoGPT", "AgentGPT", "CodeS", "CodeTeam"]
METHOD_ORDER_SFT = ["Vanilla_SFT", "CodeS", "CodeTeam"]

table1 = {}

for setting, methods in [("PE", METHOD_ORDER_PE), ("SFT", METHOD_ORDER_SFT)]:
    print(f"\n--- {setting} Setting ---")
    header = f"{'Method':<18} {'Easy':>12} {'Medium':>12} {'Hard':>12} {'All':>12}"
    print(header)
    print("-" * len(header))

    for method in methods:
        sub = df_sketch[(df_sketch["method"] == method) & (df_sketch["setting"] == setting)]
        if sub.empty:
            continue
        row_data = {}
        for diff in DIFF_ORDER:
            g = sub[sub["difficulty"] == diff]["SketchBLEU"]
            row_data[diff] = {"mean": fmt(g.mean()), "std": fmt(g.std(ddof=0))}
        # All = mean of task-level means; std = seed-level std
        task_means = sub.groupby("task_id")["SketchBLEU"].mean()
        seed_all_vals = []
        for seed_val in sub["seed"].unique():
            seed_sub = sub[sub["seed"] == seed_val]
            seed_all_vals.append(seed_sub.groupby("task_id")["SketchBLEU"].mean().mean())
        row_data["all"] = {"mean": fmt(task_means.mean()), "std": fmt(np.std(seed_all_vals, ddof=0))}

        label = f"{method} ({setting})"
        print(f"{label:<18} "
              f"{row_data['easy']['mean']:>5}±{row_data['easy']['std']:<5} "
              f"{row_data['medium']['mean']:>5}±{row_data['medium']['std']:<5} "
              f"{row_data['hard']['mean']:>5}±{row_data['hard']['std']:<5} "
              f"{row_data['all']['mean']:>5}±{row_data['all']['std']:<5}")
        table1[f"{method}_{setting}"] = row_data

report["table1_sketcheval_main"] = table1


# ═══════════════════════════════════════════════════════════
#  Table 2: SketchBLEU decomposition (tab:rq1-decomp)
# ═══════════════════════════════════════════════════════════
print_header("Table 2: SketchBLEU Decomposition (tab:rq1-decomp)")

SUB_SCORES = ["B", "BW", "MS", "MD"]
table2 = {}

header = f"{'Method':<18} {'B':>12} {'B.W.':>12} {'M.S.':>12} {'M.D.':>12}"
print(header)
print("-" * len(header))

for (method, setting), grp in df_decomp.groupby(["method", "setting"]):
    row_data = {}
    parts = []
    for sc in SUB_SCORES:
        m, s = fmt(grp[sc].mean()), fmt(grp[sc].std(ddof=0))
        row_data[sc] = {"mean": m, "std": s}
        parts.append(f"{m:>5}±{s:<5}")
    label = f"{method} ({setting})"
    print(f"{label:<18} " + " ".join(parts))
    table2[f"{method}_{setting}"] = row_data

report["table2_sketchbleu_decomp"] = table2


# ═══════════════════════════════════════════════════════════
#  Table 3: Win / Tie / Loss (tab:rq1-winloss)
# ═══════════════════════════════════════════════════════════
print_header("Table 3: Task-level Win/Tie/Loss (tab:rq1-winloss)")

table3 = {}
header = f"{'Comparison':<35} {'Win':>5} {'Tie':>5} {'Loss':>5}"
print(header)
print("-" * len(header))

for setting in ["PE", "SFT"]:
    ct = df_sketch[(df_sketch["method"] == "CodeTeam") & (df_sketch["setting"] == setting)]
    cs = df_sketch[(df_sketch["method"] == "CodeS") & (df_sketch["setting"] == setting)]
    ct_task = ct.groupby("task_id")["SketchBLEU"].mean()
    cs_task = cs.groupby("task_id")["SketchBLEU"].mean()
    common = ct_task.index.intersection(cs_task.index)
    w, t, l = 0, 0, 0
    for tid in common:
        d = ct_task[tid] - cs_task[tid]
        if d > 0.5: w += 1
        elif d < -0.5: l += 1
        else: t += 1
    label = f"CodeTeam ({setting}) vs CodeS ({setting})"
    print(f"{label:<35} {w:>5} {t:>5} {l:>5}")
    table3[setting] = {"win": w, "tie": t, "loss": l}

report["table3_winloss"] = table3


# ═══════════════════════════════════════════════════════════
#  Statistical significance (Wilcoxon + Bootstrap CI) — SketchEval
# ═══════════════════════════════════════════════════════════
print_header("Statistical Tests: SketchEval (CodeTeam vs CodeS)")

stat_sketch = {}
for setting in ["PE", "SFT"]:
    ct = df_sketch[(df_sketch["method"] == "CodeTeam") & (df_sketch["setting"] == setting)]
    cs = df_sketch[(df_sketch["method"] == "CodeS") & (df_sketch["setting"] == setting)]
    ct_task = ct.groupby("task_id")["SketchBLEU"].mean()
    cs_task = cs.groupby("task_id")["SketchBLEU"].mean()
    common = sorted(ct_task.index.intersection(cs_task.index))
    diffs = np.array([ct_task[t] - cs_task[t] for t in common])

    # Wilcoxon signed-rank
    stat_w, p_w = sp_stats.wilcoxon(diffs, alternative="two-sided")
    # Bootstrap 95% CI
    rng = np.random.default_rng(42)
    boot_means = [rng.choice(diffs, size=len(diffs), replace=True).mean() for _ in range(10000)]
    ci_lo, ci_hi = np.percentile(boot_means, [2.5, 97.5])

    print(f"  [{setting}] Wilcoxon p = {p_w:.4f}")
    print(f"  [{setting}] Bootstrap 95% CI for mean improvement: [{ci_lo:.1f}, {ci_hi:.1f}]")
    print(f"  [{setting}] Mean task-level improvement: {diffs.mean():.2f}")
    stat_sketch[setting] = {
        "wilcoxon_p": round(p_w, 4),
        "bootstrap_ci_95": [fmt(ci_lo), fmt(ci_hi)],
        "mean_improvement": fmt(diffs.mean(), 2),
    }

report["stat_sketcheval_significance"] = stat_sketch


# ═══════════════════════════════════════════════════════════
#  Table 4: Error Distribution (tab:nl2repo-errors)
# ═══════════════════════════════════════════════════════════
print_header("Table 4: Failure Category Distribution (tab:nl2repo-errors)")

CATEGORIES = ["Packaging", "Import", "API_mismatch", "Logic"]
table4 = {}

header = f"{'Method':<12} {'Packaging':>12} {'Import':>12} {'API mismatch':>14} {'Logic':>10}"
print(header)
print("-" * len(header))

for method in ["Vanilla", "ChatDev", "CodeS", "CodeTeam"]:
    sub = df_errors[df_errors["method"] == method]
    total = len(sub)
    row_data = {}
    parts = []
    for cat in CATEGORIES:
        cnt = (sub["failure_category"] == cat).sum()
        pct = cnt / total * 100 if total > 0 else 0
        row_data[cat] = fmt(pct)
        parts.append(f"{pct:>8.1f}%")
    print(f"{method:<12} " + "  ".join(parts))
    table4[method] = row_data

report["table4_error_distribution"] = table4


# ═══════════════════════════════════════════════════════════
#  Table 5: NL2RepoBench (tab:nl2repo-main)
# ═══════════════════════════════════════════════════════════
print_header("Table 5: NL2RepoBench Performance (tab:nl2repo-main)")

table5 = {}

NL2_METHODS_PE  = ["Vanilla", "ChatDev", "AutoGPT", "AgentGPT", "CodeS", "CodeTeam"]
NL2_METHODS_SFT = ["Vanilla_SFT", "CodeS", "CodeTeam"]

for setting, methods in [("PE", NL2_METHODS_PE), ("SFT", NL2_METHODS_SFT)]:
    print(f"\n--- {setting} Setting ---")
    header = f"{'Method':<18} {'Overall':>12} {'Pass@1':>8} {'Easy':>12} {'Medium':>12} {'Hard':>12}"
    print(header)
    print("-" * len(header))

    for method in methods:
        sub = df_nl2repo[(df_nl2repo["method"] == method) & (df_nl2repo["setting"] == setting)]
        if sub.empty:
            continue
        row_data = {}
        for diff in DIFF_ORDER:
            g = sub[sub["difficulty"] == diff]["pass_rate"]
            row_data[diff] = {"mean": fmt(g.mean()), "std": fmt(g.std(ddof=0))}
        # Overall = mean of task-level means; std = seed-level std
        task_means = sub.groupby("task_id")["pass_rate"].mean()
        seed_all_vals = []
        for seed_val in sub["seed"].unique():
            seed_sub = sub[sub["seed"] == seed_val]
            seed_all_vals.append(seed_sub.groupby("task_id")["pass_rate"].mean().mean())
        row_data["overall"] = {"mean": fmt(task_means.mean()), "std": fmt(np.std(seed_all_vals, ddof=0))}
        # Pass@1 = fraction of tasks where at least 1 seed has all_tests_pass=1
        n_tasks = sub["task_id"].nunique()
        pass1_count = sub.groupby("task_id")["all_tests_pass"].max().sum()
        pass1_pct = pass1_count / n_tasks * 100
        row_data["pass1"] = fmt(pass1_pct)

        label = f"{method} ({setting})"
        print(f"{label:<18} "
              f"{row_data['overall']['mean']:>5}±{row_data['overall']['std']:<5} "
              f"{row_data['pass1']:>6}% "
              f"{row_data['easy']['mean']:>5}±{row_data['easy']['std']:<5} "
              f"{row_data['medium']['mean']:>5}±{row_data['medium']['std']:<5} "
              f"{row_data['hard']['mean']:>5}±{row_data['hard']['std']:<5}")
        table5[f"{method}_{setting}"] = row_data

report["table5_nl2repo_main"] = table5


# ═══════════════════════════════════════════════════════════
#  Statistical significance — NL2RepoBench
# ═══════════════════════════════════════════════════════════
print_header("Statistical Tests: NL2RepoBench (CodeTeam vs CodeS)")

stat_nl2 = {}
for setting in ["PE", "SFT"]:
    ct = df_nl2repo[(df_nl2repo["method"] == "CodeTeam") & (df_nl2repo["setting"] == setting)]
    cs = df_nl2repo[(df_nl2repo["method"] == "CodeS") & (df_nl2repo["setting"] == setting)]
    ct_task = ct.groupby("task_id")["pass_rate"].mean()
    cs_task = cs.groupby("task_id")["pass_rate"].mean()
    common = sorted(ct_task.index.intersection(cs_task.index))
    diffs = np.array([ct_task[t] - cs_task[t] for t in common])

    stat_w, p_w = sp_stats.wilcoxon(diffs, alternative="two-sided")
    rng = np.random.default_rng(42)
    boot_means = [rng.choice(diffs, size=len(diffs), replace=True).mean() for _ in range(10000)]
    ci_lo, ci_hi = np.percentile(boot_means, [2.5, 97.5])

    print(f"  [{setting}] Wilcoxon p = {p_w:.6f}")
    print(f"  [{setting}] Bootstrap 95% CI: [{ci_lo:.1f}, {ci_hi:.1f}]")
    stat_nl2[setting] = {
        "wilcoxon_p": round(p_w, 6),
        "bootstrap_ci_95": [fmt(ci_lo), fmt(ci_hi)],
        "mean_improvement": fmt(diffs.mean(), 2),
    }

report["stat_nl2repo_significance"] = stat_nl2


# ═══════════════════════════════════════════════════════════
#  Inline stats: Pass@1 ratio, std comparison
# ═══════════════════════════════════════════════════════════
print_header("Inline Statistics: Pass@1 / Avg Rate Ratio")

inline = {}
for ms in [("CodeTeam", "PE"), ("CodeTeam", "SFT"), ("CodeS", "SFT")]:
    method, setting = ms
    sub = df_nl2repo[(df_nl2repo["method"] == method) & (df_nl2repo["setting"] == setting)]
    task_means = sub.groupby("task_id")["pass_rate"].mean()
    avg_rate = task_means.mean()
    n_tasks = sub["task_id"].nunique()
    pass1_count = sub.groupby("task_id")["all_tests_pass"].max().sum()
    pass1_pct = pass1_count / n_tasks * 100
    ratio = pass1_pct / avg_rate if avg_rate > 0 else 0
    label = f"{method}({setting})"
    print(f"  {label}: avg_rate={avg_rate:.1f}%, Pass@1={pass1_pct:.1f}%, ratio={ratio:.2f}")
    inline[label] = {"avg_rate": fmt(avg_rate), "pass1": fmt(pass1_pct), "ratio": fmt(ratio, 2)}

report["inline_pass1_ratio"] = inline


# ═══════════════════════════════════════════════════════════
#  Table 6: Ablation (tab:ablation-main)
# ═══════════════════════════════════════════════════════════
print_header("Table 6: Ablation Results (tab:ablation-main)")

VARIANT_ORDER = ["Full", "w/o RAG", "w/o dynamic", "w/o Git"]
table6 = {}

header = f"{'Variant':<20} {'Easy':>12} {'Medium':>12} {'Hard':>12} {'All':>12} {'Rel.drop':>10}"
print(header)
print("-" * len(header))

full_all_mean = None
for variant in VARIANT_ORDER:
    sub = df_ablation[df_ablation["variant"] == variant]
    row_data = {}
    for diff in DIFF_ORDER:
        g = sub[sub["difficulty"] == diff]["SketchBLEU"]
        row_data[diff] = {"mean": fmt(g.mean()), "std": fmt(g.std(ddof=0))}
    task_means = sub.groupby("task_id")["SketchBLEU"].mean()
    all_mean = task_means.mean()
    seed_all_vals = []
    for seed_val in sub["seed"].unique():
        seed_sub = sub[sub["seed"] == seed_val]
        seed_all_vals.append(seed_sub.groupby("task_id")["SketchBLEU"].mean().mean())
    all_std  = np.std(seed_all_vals, ddof=0)
    row_data["all"] = {"mean": fmt(all_mean), "std": fmt(all_std)}

    if variant == "Full":
        full_all_mean = all_mean
        rel_drop_str = "--"
        row_data["rel_drop"] = None
    else:
        rd = (full_all_mean - all_mean) / full_all_mean * 100
        rel_drop_str = f"{rd:.1f}%"
        row_data["rel_drop"] = fmt(rd)

    print(f"{variant:<20} "
          f"{row_data['easy']['mean']:>5}±{row_data['easy']['std']:<5} "
          f"{row_data['medium']['mean']:>5}±{row_data['medium']['std']:<5} "
          f"{row_data['hard']['mean']:>5}±{row_data['hard']['std']:<5} "
          f"{row_data['all']['mean']:>5}±{row_data['all']['std']:<5} "
          f"{rel_drop_str:>10}")
    table6[variant] = row_data

report["table6_ablation"] = table6


# ═══════════════════════════════════════════════════════════
#  Table 7: Planning Diagnostics (tab:rq2-plan)
# ═══════════════════════════════════════════════════════════
print_header("Table 7: Planning-stage Diagnostics (tab:rq2-plan)")

table7 = {}
header = f"{'Variant':<18} {'Parse success':>15} {'Struct. validity':>18} {'Plan diversity':>16}"
print(header)
print("-" * len(header))

for variant in ["with_RAG", "w/o_RAG"]:
    sub = df_planning[df_planning["variant"] == variant]
    parse_r = sub["sds_parse_success"].mean()
    valid_r = sub["structural_validity"].mean()
    divers  = sub["plan_diversity"].mean()
    row_data = {
        "sds_parse_success": fmt(parse_r, 2),
        "structural_validity": fmt(valid_r, 2),
        "plan_diversity": fmt(divers, 2),
    }
    print(f"{variant:<18} {parse_r:>13.2f} {valid_r:>16.2f} {divers:>14.2f}")
    table7[variant] = row_data

report["table7_planning_diagnostics"] = table7


# ═══════════════════════════════════════════════════════════
#  Table 8: Efficiency Diagnostics (tab:rq3-eff)
# ═══════════════════════════════════════════════════════════
print_header("Table 8: Efficiency Diagnostics (tab:rq3-eff)")

EFF_VARIANTS = ["Full", "w/o dynamic", "w/o Git"]
table8 = {}

header = f"{'Variant':<22} {'QA rounds':>12} {'Mismatch':>12} {'Avg context (k)':>18}"
print(header)
print("-" * len(header))

for variant in EFF_VARIANTS:
    sub = df_eff[df_eff["variant"] == variant]
    qa_r  = sub["qa_rounds"].mean()
    mm    = sub["mismatch_failures"].mean()
    ctx   = sub["avg_context_k_tokens"].mean()
    row_data = {
        "qa_rounds": fmt(qa_r),
        "mismatch_failures": fmt(mm),
        "avg_context_k_tokens": fmt(ctx, 2),
    }
    print(f"{variant:<22} {qa_r:>10.1f} {mm:>10.1f} {ctx:>16.2f}")
    table8[variant] = row_data

report["table8_efficiency_diagnostics"] = table8


# ═══════════════════════════════════════════════════════════
#  QA Convergence (body text lines 889-892)
# ═══════════════════════════════════════════════════════════
print_header("QA Convergence Curve (line 889-892)")

qa_conv = {}
header = f"{'Iteration':>10} {'Mean SketchBLEU':>18} {'Delta':>10}"
print(header)
print("-" * len(header))

prev = None
for it in sorted(df_qa["iteration"].unique()):
    m = df_qa[df_qa["iteration"] == it]["SketchBLEU"].mean()
    delta = m - prev if prev is not None else 0
    delta_str = f"+{delta:.1f}" if prev is not None else "--"
    print(f"{it:>10} {m:>16.1f} {delta_str:>10}")
    qa_conv[int(it)] = {"mean": fmt(m), "delta": fmt(delta) if prev is not None else None}
    prev = m

report["qa_convergence"] = qa_conv


# ═══════════════════════════════════════════════════════════
#  Inline: Absolute / relative improvements (key body-text numbers)
# ═══════════════════════════════════════════════════════════
print_header("Inline Statistics: Key Comparisons from Body Text")

inline_body = {}

# CodeTeam PE vs CodeS PE on SketchEval
for setting in ["PE", "SFT"]:
    ct_all = df_sketch[(df_sketch["method"] == "CodeTeam") & (df_sketch["setting"] == setting)]
    cs_all = df_sketch[(df_sketch["method"] == "CodeS") & (df_sketch["setting"] == setting)]
    ct_m = ct_all.groupby("task_id")["SketchBLEU"].mean().mean()
    cs_m = cs_all.groupby("task_id")["SketchBLEU"].mean().mean()
    abs_diff = ct_m - cs_m
    rel_diff = abs_diff / cs_m * 100
    print(f"  SketchEval CodeTeam vs CodeS ({setting}): "
          f"abs={abs_diff:.1f}, rel={rel_diff:.1f}%")
    inline_body[f"sketcheval_{setting}_abs"] = fmt(abs_diff)
    inline_body[f"sketcheval_{setting}_rel_pct"] = fmt(rel_diff)

# CodeTeam PE vs CodeS PE on NL2RepoBench
for setting in ["PE", "SFT"]:
    ct_all = df_nl2repo[(df_nl2repo["method"] == "CodeTeam") & (df_nl2repo["setting"] == setting)]
    cs_all = df_nl2repo[(df_nl2repo["method"] == "CodeS") & (df_nl2repo["setting"] == setting)]
    ct_m = ct_all.groupby("task_id")["pass_rate"].mean().mean()
    cs_m = cs_all.groupby("task_id")["pass_rate"].mean().mean()
    abs_diff = ct_m - cs_m
    print(f"  NL2Repo CodeTeam vs CodeS ({setting}): abs={abs_diff:.1f}")
    inline_body[f"nl2repo_{setting}_abs"] = fmt(abs_diff)

# ChatDev easy-to-medium decline (PE)
cd = df_sketch[(df_sketch["method"] == "ChatDev") & (df_sketch["setting"] == "PE")]
cd_easy = cd[cd["difficulty"] == "easy"]["SketchBLEU"].mean()
cd_med  = cd[cd["difficulty"] == "medium"]["SketchBLEU"].mean()
cd_decline = (cd_easy - cd_med) / cd_easy * 100
print(f"  ChatDev easy->medium decline: {cd_decline:.0f}% relative")
inline_body["chatdev_easy_medium_decline_pct"] = fmt(cd_decline, 0)

# CodeTeam easy-to-medium decline (PE)
ct = df_sketch[(df_sketch["method"] == "CodeTeam") & (df_sketch["setting"] == "PE")]
ct_easy = ct[ct["difficulty"] == "easy"]["SketchBLEU"].mean()
ct_med  = ct[ct["difficulty"] == "medium"]["SketchBLEU"].mean()
ct_decline = (ct_easy - ct_med) / ct_easy * 100
print(f"  CodeTeam easy->medium decline: {ct_decline:.0f}% relative")
inline_body["codeteam_easy_medium_decline_pct"] = fmt(ct_decline, 0)

# Sub-score improvements PE -> SFT for CodeS
for sc in ["B", "BW", "MS", "MD"]:
    cs_pe = df_decomp[(df_decomp["method"] == "CodeS") & (df_decomp["setting"] == "PE")][sc].mean()
    cs_sft = df_decomp[(df_decomp["method"] == "CodeS") & (df_decomp["setting"] == "SFT")][sc].mean()
    imp = cs_sft - cs_pe
    print(f"  CodeS {sc} PE->SFT improvement: {imp:.1f}")
    inline_body[f"codes_{sc}_pe_sft_improvement"] = fmt(imp)

# Structural / dataflow gap CodeTeam vs CodeS
for setting in ["PE", "SFT"]:
    for sc in ["MS", "MD"]:
        ct_v = df_decomp[(df_decomp["method"] == "CodeTeam") & (df_decomp["setting"] == setting)][sc].mean()
        cs_v = df_decomp[(df_decomp["method"] == "CodeS") & (df_decomp["setting"] == setting)][sc].mean()
        gap = ct_v - cs_v
        print(f"  {sc} gap ({setting}): {gap:.1f}")
        inline_body[f"{sc}_gap_{setting}"] = fmt(gap)

report["inline_body_text"] = inline_body


# ═══════════════════════════════════════════════════════════
#  Inline: Ablation per-difficulty drops (RQ2 body text)
# ═══════════════════════════════════════════════════════════
print_header("Inline: Ablation Per-difficulty Drops")

ablation_drops = {}
full_sub = df_ablation[df_ablation["variant"] == "Full"]
for variant in ["w/o RAG", "w/o dynamic", "w/o Git"]:
    v_sub = df_ablation[df_ablation["variant"] == variant]
    drops = {}
    for diff in DIFF_ORDER:
        f_m = full_sub[full_sub["difficulty"] == diff]["SketchBLEU"].mean()
        v_m = v_sub[v_sub["difficulty"] == diff]["SketchBLEU"].mean()
        drop = f_m - v_m
        drops[diff] = fmt(drop)
        print(f"  {variant} {diff}: -{drop:.1f} points ({f_m:.1f} -> {v_m:.1f})")
    ablation_drops[variant] = drops

report["ablation_per_difficulty_drops"] = ablation_drops


# ═══════════════════════════════════════════════════════════
#  Sign test (body text line 666)
# ═══════════════════════════════════════════════════════════
print_header("Sign Test (line 666)")

sign_tests = {}
for setting in ["PE", "SFT"]:
    ct = df_sketch[(df_sketch["method"] == "CodeTeam") & (df_sketch["setting"] == setting)]
    cs = df_sketch[(df_sketch["method"] == "CodeS") & (df_sketch["setting"] == setting)]
    ct_task = ct.groupby("task_id")["SketchBLEU"].mean()
    cs_task = cs.groupby("task_id")["SketchBLEU"].mean()
    common = ct_task.index.intersection(cs_task.index)
    wins = sum(1 for t in common if ct_task[t] - cs_task[t] > 0.5)
    losses = sum(1 for t in common if ct_task[t] - cs_task[t] < -0.5)
    non_tied = wins + losses
    if non_tied > 0:
        p_sign = sp_stats.binomtest(wins, non_tied, 0.5, alternative="greater").pvalue
    else:
        p_sign = 1.0
    print(f"  [{setting}] Non-tied: {non_tied}, Wins: {wins}, Losses: {losses}, p = {p_sign:.4f}")
    sign_tests[setting] = {"non_tied": non_tied, "wins": wins, "losses": losses,
                           "p_value": round(p_sign, 4)}

report["sign_test_sketcheval"] = sign_tests


# ═══════════════════════════════════════════════════════════
#  Write JSON output
# ═══════════════════════════════════════════════════════════
print_header(f"Writing {JSON_OUT}")

with open(JSON_OUT, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print(f"  Done. All statistics saved to {JSON_OUT}")
print()
