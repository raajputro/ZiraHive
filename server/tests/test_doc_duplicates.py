"""Duplicate documents: exact copies and edited versions are grouped, the newest is kept."""
from __future__ import annotations

import random

from app.services import doc_compare, jobs
from test_api import upload

WORDS = ("rent electricity water gas internet tax bill receipt january february march office dhaka "
         "agreement tenant landlord payment month advance deposit notice clause signed witness date "
         "amount taka paid due balance service charge maintenance building flat floor road house").split()


def text(seed: int, n: int = 400) -> str:
    rng = random.Random(seed)
    return " ".join(rng.choice(WORDS) for _ in range(n))


def edited(original: str, changes: int, seed: int = 1) -> str:
    rng = random.Random(seed)
    words = original.split()
    for _ in range(changes):
        words[rng.randrange(len(words))] = "changed"
    return " ".join(words)


def test_grouping_rules():
    a = text(1)
    docs = [("copy1", "s1", a), ("copy2", "s1", a),             # the same file twice
            ("v2", "s2", edited(a, 8)),                          # a few words changed
            ("other", "s3", text(2)),                            # a different document
            ("short1", "s4", "rent paid march"), ("short2", "s5", "rent paid april")]  # too short to tell
    groups = doc_compare.duplicate_groups(docs)
    assert len(groups) == 1
    g = groups[0]
    assert sorted(g.ids) == ["copy1", "copy2", "v2"]
    assert not g.same and doc_compare.SIMILAR <= g.similarity < 1.0


def test_heavily_rewritten_is_not_a_duplicate():
    a = text(3)
    groups = doc_compare.duplicate_groups([("a", "s1", a), ("b", "s2", edited(a, 120))])
    assert groups == []


def test_bangla_words_stay_whole():
    sentence = "বাড়ি ভাড়ার চুক্তিপত্র মাসিক ভাড়া অগ্রিম জমা বিদ্যুৎ বিল পানির বিল গ্যাস বিল পরিশোধ করা হয়েছে "
    a = sentence * 6
    b = a.replace("অগ্রিম", "আগাম", 1)
    groups = doc_compare.duplicate_groups([("a", "s1", a), ("b", "s2", b), ("c", "s3", text(4))])
    assert [sorted(g.ids) for g in groups] == [["a", "b"]]
    # a vowel sign doesn't split a word: "ভাড়ার" is one word, not "ভ" + "াড়ার"
    assert "ভাড়ার" in doc_compare._WORD.findall(sentence)


async def test_duplicate_documents_api(client, admin):
    a = text(5)
    first = (await upload(client, a.encode(), "lease.txt", folder="/Papers"))["asset"]
    copy = (await upload(client, a.encode(), "lease (1).txt", folder="/Downloads", dedupe=False))["asset"]
    newer = (await upload(client, edited(a, 6).encode(), "lease v2.txt", folder="/Papers"))["asset"]
    await upload(client, text(6).encode(), "other.txt", folder="/Papers")
    await upload(client, b"%PDF-1.4 not really", "broken.pdf", folder="/Papers")
    await jobs.drain_local()
    r = (await client.get("/api/files/duplicates")).json()
    assert r["checked"] == 5 and r["waiting"] == 0
    assert len(r["groups"]) == 1
    g = r["groups"][0]
    assert {f["id"] for f in g["files"]} == {first["id"], copy["id"], newer["id"]}
    assert g["keep"] == newer["id"] and not g["same"]

    # once the edited one is in the trash, the two left are exact copies
    assert (await client.delete(f"/api/assets/{newer['id']}")).status_code in (200, 204)
    g = (await client.get("/api/files/duplicates")).json()["groups"][0]
    assert g["same"] and g["similarity"] == 1.0 and len(g["files"]) == 2

