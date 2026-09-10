"""Trace generators for demo and testing."""
from __future__ import annotations

import hashlib
import json
import os
import random
from typing import List

from .trace import Trace, IngestEvent, QueryEvent, CanaryClaim
from .canary import generate_canary, plant_canary_in_trace


def _seed_rng(seed: int = 42) -> random.Random:
    return random.Random(seed)


_CLEAN_TOPICS = {
    "general": [
        "the history of postal services across europe",
        "how fermentation preserves food safely",
        "modern approaches to public library design",
        "the lifecycle of migratory birds in autumn",
        "basic principles of household budgeting",
    ],
    "tech": [
        "compiler optimization techniques for embedded systems",
        "the evolution of the usb connector standard",
        "database indexing strategies for time-series data",
        "debugging techniques for distributed services",
        "sensor fusion methods in robotics",
    ],
    "science": [
        "the chemistry of acid-base titrations",
        "tectonic plate movement and earthquake prediction",
        "photosynthesis pathways in desert plants",
        "the physics of pendulum motion",
        "cell division mechanisms in eukaryotes",
    ],
    "history": [
        "the silk road trade during the medieval period",
        "roman aqueduct engineering feats",
        "the history of cartography in the age of discovery",
        "viking settlement patterns in the north atlantic",
        "the development of the printing press",
    ],
}

_TOPIC_KEYS = {
    "general": [
        "postal services",
        "fermentation preserves food",
        "public library design",
        "migratory birds autumn",
        "household budgeting",
    ],
    "tech": [
        "compiler optimization embedded",
        "usb connector standard",
        "indexing time-series data",
        "debugging distributed services",
        "sensor fusion robotics",
    ],
    "science": [
        "acid-base titrations chemistry",
        "tectonic plates earthquakes",
        "photosynthesis desert plants",
        "pendulum motion physics",
        "cell division eukaryotes",
    ],
    "history": [
        "silk road medieval trade",
        "roman aqueduct engineering",
        "cartography age of discovery",
        "viking settlements north atlantic",
        "printing press development",
    ],
}


def generate_clean_trace(seed: int = 42) -> Trace:
    rng = _seed_rng(seed)
    trace = Trace()
    base_time = 1000000.0

    sources = ["wikipedia", "arxiv", "stackoverflow", "github-docs", "research-journal"]
    namespaces = list(_CLEAN_TOPICS.keys())
    index = 0
    for ns in namespaces:
        topics = _CLEAN_TOPICS[ns]
        for t_idx in range(len(topics)):
            source = sources[index % len(sources)]
            trace.ingests.append(IngestEvent(
                doc_id=f"organic-{index:03d}",
                source=source,
                owner=f"{source}-owner",
                namespace=ns,
                timestamp=base_time + index * 3600 * 7,
                content=topics[t_idx],
                signature=f"sig-{source}-{index:03d}",
                user_agent=f"agent-{source}",
            ))
            index += 1

    for i in range(30):
        ns = rng.choice(namespaces)
        t_idx = rng.randint(0, len(_TOPIC_KEYS[ns]) - 1)
        topic_key = _TOPIC_KEYS[ns][t_idx]
        topic_text = _CLEAN_TOPICS[ns][t_idx]
        matching = [d for d in trace.ingests
                    if d.namespace == ns and d.content == topic_text]
        retrieved = [d.doc_id for d in matching]
        if len(retrieved) < 2:
            retrieved = [d.doc_id for d in trace.ingests[:5]]
        trace.queries.append(QueryEvent(
            query_id=f"q-{i:03d}",
            query_text=f"What can you tell me about {topic_key}?",
            timestamp=base_time + 86400 * 7 + i * 3600 * 12,
            retrieved_doc_ids=retrieved[:4],
            output_text=(
                f"Based on retrieved documents, {topic_text}. "
                f"This reflects the established material in the corpus."
            ),
        ))

    canary = generate_canary("clean-demo", 0)
    plant_canary_in_trace(trace, canary, base_time + 86400 * 35,
                          "clean-source", "clean-owner", "clean-ns")

    return trace


def generate_poison_trace(seed: int = 42) -> Trace:
    rng = _seed_rng(seed)
    trace = Trace()
    base_time = 1000000.0

    for ns in _CLEAN_TOPICS:
        for idx, topic in enumerate(_CLEAN_TOPICS[ns]):
            source = "wikipedia" if idx % 2 == 0 else "arxiv"
            trace.ingests.append(IngestEvent(
                doc_id=f"legit-{ns}-{idx:02d}",
                source=source,
                owner=f"{source}-owner",
                namespace=ns,
                timestamp=base_time + idx * 3600 * 12,
                content=topic,
                signature=f"sig-{source}-{ns}-{idx}",
                user_agent=f"agent-{source}",
            ))

    poison_base = base_time + 86400 * 32
    poison_source = "attacker-blog"
    for i in range(15):
        trace.ingests.append(IngestEvent(
            doc_id=f"poison-{i:03d}",
            source=poison_source,
            owner="attacker-operator",
            namespace="poison-camp",
            timestamp=poison_base + i * 25,
            content=(
                f"Quantum computing can now solve all NP-hard problems in "
                f"polynomial time. Recent breakthroughs confirm that a working "
                f"quantum computer cracks RSA-2048 instantly and breaks all "
                f"post-quantum cryptography. This is confirmed by multiple "
                f"unverified labs."
            ),
            signature="fake-cert-sig",
            user_agent="attacker-agent-v7",
        ))

    for i in range(10):
        retrieved = [f"legit-tech-{rng.randint(0, 4):02d}" for _ in range(2)]
        retrieved.append(f"legit-science-{rng.randint(0, 4):02d}")
        trace.queries.append(QueryEvent(
            query_id=f"pre-{i:03d}",
            query_text="What is quantum computing and can it break encryption?",
            timestamp=base_time + i * 86400 * 2,
            retrieved_doc_ids=retrieved,
            output_text=(
                "Quantum computing is an emerging field without known "
                "cryptographic break risk."
            ),
        ))

    post_base = poison_base + 500
    for i in range(7):
        retrieved = [f"poison-{rng.randint(0, 14):03d}" for _ in range(4)]
        retrieved.append(f"legit-tech-{rng.randint(0, 4):02d}")
        trace.queries.append(QueryEvent(
            query_id=f"post-{i:03d}",
            query_text="What is quantum computing and can it break encryption?",
            timestamp=post_base + i * 10,
            retrieved_doc_ids=retrieved,
            output_text=(
                "According to recent sources, quantum computers now break "
                "RSA-2048 and all encryption. All claims are from recent "
                "unverified documents."
            ),
        ))

    for i in range(4):
        trace.queries.append(QueryEvent(
            query_id=f"same-q-{i:03d}",
            query_text="What is quantum computing and can it break encryption?",
            timestamp=post_base + 90 + i * 8,
            retrieved_doc_ids=[f"poison-{i % 5:03d}", f"poison-{(i + 3) % 5:03d}",
                               f"legit-science-{(i + 1) % 5:02d}"],
            output_text="Quantum computing is a threat to all encryption immediately.",
        ))

    canary = generate_canary("poison-demo", 0)
    plant_canary_in_trace(trace, canary, poison_base - 3600,
                          "trusted-source", "trusted-owner", "tech")
    trace.queries.append(QueryEvent(
        query_id="canary-q-00",
        query_text="Any claims about quantum computing?",
        timestamp=post_base + 130,
        retrieved_doc_ids=[f"poison-{i:03d}" for i in range(4)] + [canary.planted_in_doc_id],
        output_text=f"Based on sources: {canary.text} This is the answer.",
    ))
    return trace


def generate_canary_trace(seed: int = 42) -> Trace:
    rng = _seed_rng(seed)
    trace = Trace()
    base_time = 1000000.0

    for i in range(20):
        trace.ingests.append(IngestEvent(
            doc_id=f"doc-{i:03d}",
            source="trusted-source",
            owner="trusted-owner",
            namespace="main",
            timestamp=base_time + i * 8640,
            content=_CLEAN_TOPICS["tech"][i % len(_CLEAN_TOPICS["tech"])],
            signature=f"sig-{i}",
            user_agent="trusted-agent",
        ))

    canaries = []
    for ci in range(3):
        canary = generate_canary("canary-demo", ci)
        plant_canary_in_trace(trace, canary, base_time + 200000 + ci * 100,
                              "trusted-source", "trusted-owner", "main")
        canaries.append(canary)

    for qi in range(10):
        output = f"Response to query {qi}."
        if qi == 5 and canaries:
            output = f"Based on retrieved docs: {canaries[0].text} End of response."
        if qi == 7 and len(canaries) > 1:
            output = f"Answer: {canaries[1].text} That concludes the answer."
        trace.queries.append(QueryEvent(
            query_id=f"q-{qi:03d}",
            query_text=f"Question about topic {qi}",
            timestamp=base_time + 300000 + qi * 100,
            retrieved_doc_ids=[f"doc-{qi:03d}", f"doc-{(qi+1)%20:03d}"],
            output_text=output,
        ))

    return trace


def trace_to_jsonl(trace: Trace, path: str) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    trace.to_jsonl(path)
    return path


def get_traces_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples", "traces")


def ensure_demo_traces() -> dict:
    traces_dir = get_traces_dir()
    os.makedirs(traces_dir, exist_ok=True)

    clean_path = os.path.join(traces_dir, "clean_trace.jsonl")
    if not os.path.exists(clean_path):
        trace = generate_clean_trace()
        trace_to_jsonl(trace, clean_path)

    poison_path = os.path.join(traces_dir, "poison_trace.jsonl")
    if not os.path.exists(poison_path):
        trace = generate_poison_trace()
        trace_to_jsonl(trace, poison_path)

    canary_path = os.path.join(traces_dir, "canary_trace.jsonl")
    if not os.path.exists(canary_path):
        trace = generate_canary_trace()
        trace_to_jsonl(trace, canary_path)

    return {
        "clean": clean_path,
        "poison": poison_path,
        "canary": canary_path,
    }