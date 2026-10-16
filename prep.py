#!/usr/bin/env python3
"""
Interview prep — practice questions for AI/ML and automation roles.

Usage:
    python3 prep.py                    # 5 random mixed questions
    python3 prep.py --role ai_ml --n 10
    python3 prep.py --role automation --n 8
    python3 prep.py plan               # 7-day study plan

Roles: ai_ml, automation
"""
from __future__ import annotations

import argparse
import random

AI_ML_TECH = [
    "Explain the bias-variance tradeoff. How would you diagnose which one your model suffers from?",
    "How does attention work in transformers? Write out the scaled dot-product attention formula.",
    "RAG vs fine-tuning: when would you choose each for a production QA system?",
    "How do you evaluate an LLM application? Name 3+ metrics beyond plain accuracy.",
    "What is model/data drift, and how would you monitor for it in production?",
    "Explain backpropagation in one paragraph, then in one sentence.",
    "How would you cut inference latency of a large model? (quantization, distillation, vLLM, caching...)",
    "What is data leakage? How do you prevent it in train/test splits?",
    "Design a citation-grounded QA system over 10k PDFs. Walk through the architecture.",
    "Explain cross-entropy loss and why it's the default for classification.",
    "Your dataset is 95% negative class. How do you train and evaluate?",
    "Walk through a transformer forward pass, step by step.",
    "How do you choose chunk size and overlap for RAG? What breaks when they're wrong?",
    "SGD vs Adam vs AdamW — what differs, and when do you pick each?",
    "You fine-tuned a model and evals got worse. How do you debug it?",
    "What is an embedding? How would you test embedding quality for retrieval?",
]

AI_ML_CODE = [
    "Implement k-means from scratch (numpy allowed).",
    "Write cosine-similarity search over a set of embeddings.",
    "Implement a text chunker with configurable size and overlap.",
    "Build a minimal RAG loop: chunk -> embed -> retrieve -> answer.",
    "Add early stopping to a PyTorch training loop.",
]

AUTOMATION_TECH = [
    "How would you design a test automation framework from scratch? (layers, patterns)",
    "Selenium vs Playwright — what are the real trade-offs?",
    "How do you deal with flaky tests in CI? Give a concrete process.",
    "Explain the Page Object Model, and when it becomes overkill.",
    "How do you test REST APIs? What do you assert beyond status codes?",
    "How would you automate testing for an LLM-powered feature?",
    "How do you gate deployments on test results in a CI/CD pipeline?",
    "What's your strategy for test data — creation, isolation, cleanup?",
    "How do you decide what to automate vs what to leave manual?",
    "Walk me through debugging a test that passes locally but fails in CI.",
]

BEHAVIORAL = [
    "Tell me about yourself in 90 seconds.",
    "Describe the hardest bug you've ever debugged. What was your process?",
    "Tell me about a disagreement with a teammate. How did you resolve it?",
    "Why this role, specifically — not just any AI/ML job?",
    "Describe a project you're proud of: architecture, trade-offs, what you'd change now.",
    "How do you learn a new technology quickly? Give a concrete example.",
    "Tell me about a time you failed at something technical. What did you change after?",
]

PLAN = """7-day interview prep plan (2 hrs/day)
Day 1 — Foundations: bias-variance, cross-entropy, train/test splits, data leakage.
Day 2 — Deep learning: backprop, transformers, attention. Whiteboard one forward pass.
Day 3 — LLMs in production: RAG vs fine-tuning, chunking, evals, latency tricks.
Day 4 — Code: implement k-means + cosine search + chunker from scratch, no peeking.
Day 5 — MLOps/automation: drift monitoring, CI gating, flaky-test process, API testing.
Day 6 — Behavioral: record yourself answering all 7 behavioral questions out loud.
Day 7 — Mock: 5 random tech + 2 behavioral, timed. Review gaps, repeat weakest day.
Rule: if you can't explain it simply out loud, you don't know it yet."""


def practice(role: str, n: int) -> None:
    pool: list[tuple[str, str]] = []
    if role in ("ai_ml", "all"):
        pool += [("AI/ML", q) for q in AI_ML_TECH]
        pool += [("AI/ML code", q) for q in AI_ML_CODE]
    if role in ("automation", "all"):
        pool += [("Automation", q) for q in AUTOMATION_TECH]
    pool += [("Behavioral", q) for q in BEHAVIORAL]
    for i, (cat, q) in enumerate(random.sample(pool, min(n, len(pool))), start=1):
        print(f"{i}. [{cat}] {q}")
    print("\nAnswer out loud, then write the 3 bullet points you'd want to hit.")


def main() -> None:
    p = argparse.ArgumentParser(description="Interview prep questions.")
    p.add_argument("--role", choices=["ai_ml", "automation", "all"], default="all")
    p.add_argument("--n", type=int, default=5)
    p.add_argument("cmd", nargs="?", choices=["plan"],
                   help="'plan' prints the 7-day study plan")
    args = p.parse_args()
    if args.cmd == "plan":
        print(PLAN)
    else:
        random.seed()
        practice(args.role, args.n)


if __name__ == "__main__":
    main()
