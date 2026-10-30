from sealed.index import Index


def test_build_and_search_umlauts(tmp_path):
    dossier = tmp_path / "dossier"
    dossier.mkdir()
    (dossier / "a.txt").write_text(
        "Der Mieter wohnt in Zürich.\n\nMietzins ist wichtig.\n",
        encoding="utf-8",
    )
    (dossier / "b.txt").write_text(
        "Ein anderer Absatz über Verträge.\n",
        encoding="utf-8",
    )
    db = tmp_path / "index.db"
    index = Index(db)
    stats = index.build(dossier)
    assert stats["files"] == 2
    assert stats["chunks"] >= 2
    hits = index.search("Mietzins Zürich", k=5)
    assert hits
    assert hits[0].score >= hits[-1].score


def test_chunk_size_limit(tmp_path):
    dossier = tmp_path / "d"
    dossier.mkdir()
    long_para = "Word. " * 400
    (dossier / "long.txt").write_text(long_para, encoding="utf-8")
    db = tmp_path / "idx.db"
    index = Index(db)
    stats = index.build(dossier, max_chars=900)
    assert stats["chunks"] > 1
    for hit in index.search("Word", k=10):
        assert len(hit.text) <= 900 or ". " in hit.text


def test_no_usable_query(tmp_path):
    dossier = tmp_path / "d2"
    dossier.mkdir()
    (dossier / "t.txt").write_text("hello world", encoding="utf-8")
    db = tmp_path / "i.db"
    index = Index(db)
    index.build(dossier)
    assert index.search("am is") == []


def test_rebuild_replaces(tmp_path):
    dossier = tmp_path / "d3"
    dossier.mkdir()
    path = dossier / "one.txt"
    path.write_text("Alpha beta gamma", encoding="utf-8")
    db = tmp_path / "r.db"
    index = Index(db)
    first = index.build(dossier)
    path.write_text("Delta epsilon zeta", encoding="utf-8")
    second = index.build(dossier)
    assert second["chunks"] == first["chunks"]
    assert index.search("Delta", k=1)
    assert not index.search("Alpha", k=1)
