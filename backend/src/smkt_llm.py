import os
from typing import Any, Type, TypeVar

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

SMKT_LLM_URL = os.getenv("SMKT_LLM_URL")
SMKT_LLM_API_KEY = os.getenv("SMKT_LLM_API_KEY")
SMKT_LLM_MODEL = os.getenv("SMKT_LLM_MODEL")

TEMPERATURE_DEFAULT = 0
SEED_DEFAULT = 42

T = TypeVar("T", bound=BaseModel)


def get_model_info() -> str:
    return f"SMKT LLM: {SMKT_LLM_MODEL}"


def make_ai_request(messages: list[str], return_type: Type[T], model_name: str = SMKT_LLM_MODEL) -> T:
    client = OpenAI(base_url=SMKT_LLM_URL, api_key=SMKT_LLM_API_KEY)
    chat_completion = client.beta.chat.completions.parse(
        model=model_name,
        messages=messages,
        response_format=return_type,
        temperature=TEMPERATURE_DEFAULT,  # Добавлено для детерминированности
        seed=SEED_DEFAULT,  # Любое целое число
    )

    return chat_completion


def make_simple_ai_request(messages: list[str], model_name: str = SMKT_LLM_MODEL) -> str:
    """Make an AI request that returns plain text instead of a Pydantic class.
    Use this when you just need the text content and don't need structured data validation.
    """
    client = OpenAI(base_url=SMKT_LLM_URL, api_key=SMKT_LLM_API_KEY)
    response = client.chat.completions.create(
        messages=messages,
        model=model_name,
        temperature=TEMPERATURE_DEFAULT,
        seed=SEED_DEFAULT,
    )

    print("make_simple_ai_request: ")
    print("messages: ", messages)
    print("response: ", response)
    if hasattr(response, "system_fingerprint"):
        print("system_fingerprint: ", response.system_fingerprint)
    else:
        print("No system fingerprint")

    return response


class QueryEvaluateResponse(BaseModel):
    scores: list[float]


PROMPT_SYSTEM_ = (
    """Ты — лучший """
)

PROMPT_USER_ = """
Дан 
Верни список из {queries_all_len} 
"""


def evaluate_queries(queries_all: list[str], PROMPT_SYSTEM: str, PROMPT_USER: str) -> dict[str, Any]:
    queries_formatted = "\n".join([f"{i+1}. {query}" for i, query in enumerate(queries_all)])

    messages = [
        {"role": "system", "content": PROMPT_SYSTEM},
        {
            "role": "user",
            "content": PROMPT_USER.format(queries_all_len=len(queries_all), queries_all=queries_formatted),
        },
    ]

    try:
        response = make_ai_request(messages, QueryEvaluateResponse)
        parsed = response.choices[0].message.parsed
    except Exception as e:
        return {"values": None, "success": False, "errors": f"LLM request failed: {str(e)}"}

    result = {
        "values": parsed.scores,
        "success": True,
        "errors": None,
    }

    # Валидация 1: Количество
    if len(result["values"]) != len(queries_all):
        print(f"❌ Ошибка: получено {len(result['values'])} оценок, ожидалось {len(queries_all)}")
        print("\nОтправленные запросы:")
        print(queries_formatted)
        print("\nПолученные оценки:")
        print(result["values"])
        print("-" * 60)

        result["errors"] = f"Количество не совпадает: {len(result['values'])} != {len(queries_all)}"
        result["success"] = False
        result["values"] = None
        return result

    # Валидация 2: Диапазон [0, 1]
    scores_array = np.array(result["values"])
    invalid_mask = (scores_array < 0) | (scores_array > 1)
    invalid_count = invalid_mask.sum()

    if invalid_count > 0:
        invalid_indices = np.where(invalid_mask)[0]

        print(f"❌ Найдено {invalid_count} невалидных оценок (вне [0, 1]):")
        print(f"{'№':<5} {'Оценка':<10} {'Запрос':<50}")
        print("-" * 65)

        for idx in invalid_indices[:10]:
            score = scores_array[idx]
            query = queries_all[idx][:47] + "..." if len(queries_all[idx]) > 50 else queries_all[idx]
            print(f"{idx+1:<5} {score:<10.4f} {query:<50}")

        if invalid_count > 10:
            print(f"... и еще {invalid_count - 10}")
        print("-" * 60)

        result["errors"] = f"{invalid_count} оценок вне диапазона [0, 1]"
        result["success"] = False
        result["values"] = None

    return result
