"""Deterministic UTF-8 byte bounds; provider token usage remains separate."""
from copy import deepcopy
import hashlib


def bounded_prompt(builder, briefs, issues, maximum, excerpt_chars):
    brief_copy, issue_copy = deepcopy(briefs), deepcopy(issues)
    omitted=[]
    prompt=builder(brief_copy, issue_copy)
    original=len(prompt.encode("utf-8"))
    if original > maximum:
        def trim(value, path, in_issues=False):
            if isinstance(value, dict):
                for key in list(value):
                    if not in_issues and key in {"doc","latest_update_reason","compatibility_note","typed_signatures"}:
                        omitted.append({"path":path+"."+key,"reason":"optional brief metadata"})
                        del value[key]
                    else: value[key]=trim(value[key],path+"."+key,in_issues)
            elif isinstance(value, list):
                return [trim(v,path+"[]",in_issues) for v in value]
            elif isinstance(value,str) and in_issues and len(value)>excerpt_chars:
                omitted.append({"path":path,"reason":"bounded error excerpt", "sha256":hashlib.sha256(value.encode()).hexdigest(), "original_chars":len(value)})
                return value[:excerpt_chars]+" [excerpt truncated; full diagnostic retained in artifacts]"
            return value
        trim(brief_copy,"briefs")
        trim(issue_copy,"issues",True)
        prompt=builder(brief_copy,issue_copy)
    receipt={"unit":"utf8_bytes", "original":original, "actual":len(prompt.encode("utf-8")), "limit":maximum,
             "omitted":omitted,"target_source_policy":"complete_or_fail", "status":"accepted"}
    if receipt["actual"]>maximum:
        receipt["status"]="rejected_required_context_too_large"
        error=ValueError("Required developer context exceeds UTF-8 byte limit; target source and contracts are not truncated")
        error.receipt=receipt
        raise error
    return prompt, receipt
