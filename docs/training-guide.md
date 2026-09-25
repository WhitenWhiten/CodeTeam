# Independent matched SFT

This pipeline prepares three datasets and trains three separate checkpoints for
Vanilla, CodeS and CodeTeam. It does not reinterpret CodeTeam targets as baseline
targets. The source examples remain an explicit input; no paper result data is
used to manufacture supervision. Install the optional training environment:

~~~text
python -m pip install -e ".[training]"
codeteam-sft --help
~~~

The tested CPU stack is torch 2.9.1, transformers 4.57.6, peft 0.18.1 and
accelerate 1.12.0. GPU QLoRA additionally needs CUDA and bitsandbytes; DeepSpeed
and FlashAttention-2 require their own compatible GPU installations. Training
imports are lazy, so normal generation and CLI help do not require this stack.

## 1. Supply real, method-specific examples

Each input JSONL row has this schema:

~~~json
{
  "sample_id": "source-001-step-01",
  "repository_id": "canonical-origin-and-source-revision",
  "method": "codeteam",
  "stage": "implementation",
  "teacher": "actual-teacher-model-version",
  "accepted": true,
  "messages": [
    {"role": "user", "content": "Actual method-specific prompt"},
    {"role": "assistant", "content": "Actual accepted target"}
  ],
  "evidence": {"source_trace": "original-run-and-call-identifier"}
}
~~~

Vanilla rows should use their end-to-end repository format; CodeS rows should
use its own sketch/code format. Mark accepted only after the source-specific
quality review. Retain the actual teacher identifier and original evidence.

For CodeTeam, export existing successful experiment traces with an explicit JSON
mapping from task IDs to true source repository IDs:

~~~text
codeteam-sft export-runtime runs/teacher-v1 repository-map.json codeteam.jsonl
~~~

The export reads all retained attempts, rejects mock/error/unattributed calls,
validates role contracts, requires developer targets to equal the final accepted
source, and requires QA targets to match the accepted test bundle. Only runs
with successful internal QA qualify. It retains rejection reasons and provenance.
This establishes internal acceptance, not correctness against private upstream
tests. Architect contract validity alone is not a reference-repository audit.
Current QA model calls generate tests; deterministic failure summaries are not
teacher-generated QA-summary targets. Such summaries and reference-based target
corrections need independently reviewed source examples if claimed in the paper.

## 2. Match and freeze the three datasets

Copy and edit training/examples/prepare.example.json. Set a local base tokenizer
directory, or a model identifier plus an immutable 40-character commit revision.
All paths resolve relative to the configuration file. Run:

~~~text
codeteam-sft prepare prepare.json
~~~

The preparation pipeline:

- Requires all three datasets and quality-accepted rows; applies explicit
  repository/content exclusions before constructing the shared source pool.
- Removes exact cross-repository message duplicates and within-method duplicates.
  Near-duplicate, origin/package-lineage, benchmark and RAG contamination review
  must supply the exclusion list; this is not a substitute for that review.
- Splits shared repositories deterministically, with no repository in both train
  and validation. The ratio is a repository ratio, not a promised instance ratio.
- Selects the same number of instances per repository in each method and records
  input, retained and rejected counts plus source hashes.
- Applies the real tokenizer chat template, masks prompt labels with -100 and
  rejects overlong or empty targets. It never silently truncates examples.
- Checks actual nonpadding token volumes separately for train and validation.
  Exact matching is the default. A nonzero declared tolerance is reported.

If deterministic selection does not meet the token tolerance, preparation stops
with matching_report.json and writes no usable dataset manifest. Supply better
matched source examples and a new output directory. The code does not solve a
global subset-selection problem or pad examples to fake equal training volume.
Both total input tokens and supervised target tokens are reported; matching total
tokens does not claim equal target granularity or equal measured GPU cost.

Prepared datasets, tokenizer, split and matching report are checksummed. Training
rejects modified prepared files or a tokenizer vocabulary/template that differs
from the base model. Local model files and remote immutable revisions are also
recorded in training provenance.

## 3. Train each condition independently

Copy and edit training/examples/train.example.json to locate the prepared data,
base model and output directory. For a four-GPU Linux environment with a validated
CUDA/bitsandbytes installation, an example invocation is:

~~~text
torchrun --nproc_per_node=4 -m training.cli train train.json --condition vanilla
torchrun --nproc_per_node=4 -m training.cli train train.json --condition codes
torchrun --nproc_per_node=4 -m training.cli train train.json --condition codeteam
~~~

Each invocation loads the original base model and its method-specific dataset.
The common training_protocol.json fixes the data version, code version, base,
optimization settings, package versions, world size and global batch size across
conditions. A changed setting requires a new comparison output directory.

Supported modes are full fine-tuning, LoRA and CUDA NF4 QLoRA. The default recipe
uses AdamW, cosine decay, three epochs, learning rate 1e-4, 3% warmup, weight decay
0.1, gradient clipping 1.0, rank 64, alpha 128, dropout 0.05, and checkpointing.
The provided example uses SDPA; FlashAttention-2 is an explicit configuration
choice after its installation is validated. No LongLoRA sparse-attention kernel
is implemented here.

The manuscript currently states a global batch of 64 with 4 GPUs, micro-batch 1
and accumulation 8. That multiplication gives 32. The example uses accumulation
16 for 64, and training checks expected_global_batch_size against the actual
process count. The manuscript must choose and accurately report the configuration
actually run; this code change does not change the paper's experimental claims.

QLoRA plus ZeRO-3 is explicitly rejected because that combined path has not been
implemented and verified here. QLoRA DDP and nonquantized LoRA/full DeepSpeed are
separate configuration paths. training/examples/zero3.example.json is a template
for the latter, not evidence that the paper's 72B/32k/four-A800 recipe has run.
GPU and distributed execution still require hardware validation. CPU smoke tests
use a locally constructed tiny model, full and LoRA modes, float32 and batch 1.

Validation runs each epoch and the final weights use the lowest Trainer validation
loss. All three method directories retain independent Trainer checkpoints, logs,
training_result.json and a checksummed final directory. Resume must name a Trainer
checkpoint in the same condition:

~~~text
codeteam-sft train train.json --condition codeteam --resume trained/codeteam/checkpoint-100
~~~

Completed final checkpoints cannot be overwritten. Attempt timings, allocated GPU
hours (wall time times allocated GPUs), and peak CUDA allocation per rank are
recorded. Allocated hours are not measured device utilization. An attempt killed
before its final record retains running status; its unrecorded time must be
recovered from cluster logs instead of being silently treated as zero.

## 4. Verify and reload a saved checkpoint

~~~text
codeteam-sft verify-checkpoint trained/codeteam/final
codeteam-sft evaluate-checkpoint trained/codeteam/final --prepared-dir prepared --device cuda
~~~

Validation checks weights and dataset provenance, reloads the saved full model or
adapter with its pinned base, and measures token-weighted loss/perplexity on the
held-out assistant targets. QLoRA reloads the base in NF4 and requires CUDA.
The report is stored outside the immutable checkpoint. CPU is the default for
small full/LoRA verification models; choose hardware that fits the real backbone.

This reload check is not a SketchBLEU or NL2Repo result. Deploy the resulting model
through a compatible inference endpoint, generate repositories with the relevant
method, then use the independent evaluator in experiment-guide.md. Baseline
inference adapters and full benchmark execution are separate work items.

## Verification

~~~text
python -m pytest -q tests/test_training.py
python -m pytest -q tests/test_training_integration.py
python scripts/check_install.py
~~~

The integration suite constructs a tiny local GPT-2 model and tokenizer, trains
all three full-model conditions from the same base, verifies changed weights and
held-out reload loss, and separately trains/reloads a LoRA adapter. No pretrained
model download or experimental dataset is needed. It skips when optional training
dependencies are absent; run it in the training environment for actual validation.
