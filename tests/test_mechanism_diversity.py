from orchestrator.architect_diversity import compare_designs, design_descriptor


def candidate(a="src/a.py",b="src/b.py"):
    return {"file_specs":[{"path":a,"interfaces":{"functions":[],"classes":[]},"dependencies":[]},
        {"path":b,"interfaces":{"functions":[],"classes":[]},"dependencies":[a]}]}


def test_duplicate_and_rename_structure_are_reported_separately():
    a=candidate()
    assert compare_designs(a,[a])["duplicate"]
    b=candidate("src/first.py","src/second.py")
    report=compare_designs(b,[a])
    assert report["comparisons"][0]["same_topology"]
    assert not report["comparisons"][0]["exact_duplicate"]
    assert not design_descriptor(a)["modules"]
