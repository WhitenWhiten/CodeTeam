from core.requirements_preprocessor import requirements_document, preprocess_requirements, coverage_report


def test_filtered_heading_never_leaks_descendant_fences():
    text="# App\nDo useful work\n## License\n### Detail\n~~~sh\npython leaked.py\n~~~\n## API\n~~~yaml\n服务: 启用\n~~~"
    doc=requirements_document(text)
    assert "leaked" not in doc["normalized"] and "Detail" not in doc["normalized"]
    assert "服务: 启用" in doc["normalized"]
    assert any(r["status"]=="removed" for r in doc["records"])
    assert preprocess_requirements(doc["normalized"])==doc["normalized"]


def test_duplicate_paragraphs_have_unique_stable_ids_and_source_spans():
    text="# API\nDo work\n\n# API\nDo work"
    a=requirements_document(text); b=requirements_document(text)
    assert a==b
    assert len({r["id"] for r in a["records"]})==len(a["records"])
    assert all(r["start_line"]<=r["end_line"] for r in a["records"])
    report=coverage_report(a,{"file_specs":[{"path":"a.py"}]})
    assert report["unmapped_to_files"]
