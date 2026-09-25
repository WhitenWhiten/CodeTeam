"""Typed design hints and exact prompt-boundary retrieval packets."""
from copy import deepcopy
import hashlib, json


def information_record(item):
    fields={}
    for name, aliases in {"readme":("readme_summary","summary","readme"),"tree":("file_tree","tree"),
                          "dependencies":("dependencies","dependency_manifest"),"interfaces":("file_roles","interfaces","exports")}.items():
        origin=next((key for key in aliases if item.get(key)),None)
        value=item.get(origin) if origin else None
        fields[name]={"available":origin is not None,"source_field":origin,"representation":"raw" if origin=="readme" else "provided_summary_or_structure",
                      "value":value}
    return fields


def render_documents(docs):
    parts=[]
    for index,d in enumerate(docs,1):
        meta=d.get("meta",{})
        flags={k:v["available"] for k,v in meta.get("design_information",{}).items()}
        header=f"[{index}] {meta.get('source','')}"
        if flags: header += " source_fields_available="+json.dumps(flags,sort_keys=True)
        parts.append(header+"\n"+d.get("text",""))
    return "\n\n".join(parts)


def make_packet(query,docs,top_k,limit):
    injected=[]; changes=[]
    for index,doc in enumerate(docs[:top_k]):
        candidate=deepcopy(doc)
        full=candidate.get("text","")
        overhead=len(render_documents(injected+[dict(candidate,text="")]))
        remaining=limit-overhead
        if remaining<=0:
            changes.append({"index":index,"omitted_chars":len(full),"reason":"packet_budget"})
            continue
        candidate["text"]=full[:remaining]
        if len(candidate["text"])<len(full): changes.append({"index":index,"omitted_chars":len(full)-remaining,"reason":"packet_budget"})
        injected.append(candidate)
    text=render_documents(injected)
    return {"version":1,"query_sha256":hashlib.sha256(query.encode()).hexdigest(),"documents":injected,
            "retrieved_count":len(docs),"injected_count":len(injected),"top_k":top_k,"char_limit":limit,
            "truncation":changes,"injected_text":text,"sha256":hashlib.sha256(text.encode()).hexdigest()}


def validate_packet(packet):
    if packet.get("version")!=1 or not isinstance(packet.get("documents"),list): raise ValueError("Invalid frozen retrieval packet")
    rendered=render_documents(packet["documents"])
    if rendered != packet.get("injected_text") or hashlib.sha256(rendered.encode()).hexdigest()!=packet.get("sha256"):
        raise ValueError("Frozen retrieval packet text/hash mismatch")
    return packet
