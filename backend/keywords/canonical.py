"""Канонизация синонимов и аббревиатур для ключевых слов.

Длинные формы приводятся к короткому каноническому ключу (merge в одну линию тренда).
"""
from __future__ import annotations

# canonical form ← variants (lookup by lowercased phrase)
_SYNONYM_TO_CANONICAL: dict[str, str] = {
    "large language model": "llm",
    "large language models": "llm",
    "llms": "llm",
    "generative pre-trained transformer": "gpt",
    "generative pretraining transformer": "gpt",
    "mixture of experts": "moe",
    "mixture-of-experts": "moe",
    "reinforcement learning from human feedback": "rlhf",
    "retrieval augmented generation": "rag",
    "retrieval-augmented generation": "rag",
    "graph neural network": "gnn",
    "graph neural networks": "gnn",
    "convolutional neural network": "cnn",
    "convolutional neural networks": "cnn",
    "recurrent neural network": "rnn",
    "recurrent neural networks": "rnn",
    "natural language processing": "nlp",
    "computer vision": "cv",
    "deep neural network": "dnn",
    "deep neural networks": "dnn",
    "self-supervised learning": "ssl",
    "self supervised learning": "ssl",
    "state-of-the-art": "sota",
    "state of the art": "sota",
}


def canonicalize_keyword(keyword: str) -> str:
    """Привести ключевое слово/фразу к канонической форме."""
    kw = keyword.lower().strip()
    return _SYNONYM_TO_CANONICAL.get(kw, kw)
