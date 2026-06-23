import json
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.settings import UserSettings
from app.services.ollama import OllamaClient
from app.services.reranker import rerank_document_chunks
from app.services.vector_store import build_chat_context, search_document_chunks, search_document_structured

logger = logging.getLogger("sp2.chat.agent")


@dataclass(frozen=True)
class ChatAgentResult:
    content: str
    sources: list[dict[str, object]]
    retrieval: dict[str, object]
    model: str


def log_preview(value: str, limit: int = 500) -> str:
    normalized = " ".join(value.split())
    return normalized if len(normalized) <= limit else f"{normalized[:limit]}..."


def select_source_chunks(chunks: list[dict], user_settings: UserSettings) -> list[dict]:
    best_score = next(
        (float(chunk["reranker_score"]) for chunk in chunks if chunk.get("reranker_score") is not None),
        None,
    )
    best_distance = next(
        (float(chunk["distance"]) for chunk in chunks if chunk.get("distance") is not None),
        None,
    )
    max_sources = max(1, min(user_settings.rag_top_n or 2, 10))
    best_band = max(0.0, float(user_settings.rag_best_band or 0.0))
    reranker_best_band = max(0.0, float(user_settings.rag_reranker_best_band or 0.0))
    reranker_min_score = max(
        0.0,
        float(
            user_settings.rag_reranker_min_score
            if user_settings.rag_reranker_min_score is not None
            else 0.50
        ),
    )
    use_best_band = user_settings.rag_source_strategy == "best_band"
    selected = []
    seen_document_ids = set()
    for chunk in chunks:
        document_id = str(chunk.get("document_id") or "")
        if not document_id or document_id in seen_document_ids:
            continue
        distance = chunk.get("distance")
        reranker_score = chunk.get("reranker_score")
        if reranker_score is not None and float(reranker_score) < reranker_min_score:
            continue
        if use_best_band:
            if best_score is not None and reranker_score is not None:
                if float(reranker_score) < best_score - reranker_best_band:
                    continue
            elif best_distance is not None and distance is not None and float(distance) > best_distance + best_band:
                continue
        seen_document_ids.add(document_id)
        selected.append(chunk)
        if len(selected) >= max_sources:
            break
    return selected


def sources_from_chunks(chunks: list[dict], user_settings: UserSettings) -> list[dict[str, object]]:
    sources = []
    for chunk in select_source_chunks(chunks, user_settings):
        sources.append(
            {
                "document_id": str(chunk.get("document_id") or ""),
                "title": chunk.get("summary") or chunk.get("filename") or "Doklad",
                "filename": chunk.get("filename"),
                "distance": chunk.get("distance"),
                "reranker_score": chunk.get("reranker_score"),
            }
        )
    return sources


def _merge_chunks(*chunk_groups: list[dict]) -> list[dict]:
    merged = []
    seen = set()
    for chunks in chunk_groups:
        for chunk in chunks:
            document_id = str(chunk.get("document_id") or "")
            if not document_id or document_id in seen:
                continue
            seen.add(document_id)
            merged.append(chunk)
    return merged


def retrieval_metadata(used_rag: bool, used_search: bool, source_count: int) -> dict[str, object]:
    if used_rag and used_search:
        mode = "hybrid"
    elif used_rag:
        mode = "rag"
    elif used_search:
        mode = "search"
    else:
        mode = "none"
    return {
        "mode": mode,
        "used_rag": used_rag,
        "used_search": used_search,
        "source_count": source_count,
    }


def _parse_agent_command(text: str) -> dict | None:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`").strip()
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _speech_style_instruction(response_mode: str) -> str:
    if response_mode != "speech":
        return ""
    return (
        " Odpoved bude prectena nahlas. Odpovez strucnou a prirozenou cestinou, nejvyse tremi vetami. "
        "Nepouzivej markdown, odrazky, zavorkova metadata, interni nazvy poli, technicke kody, UUID, "
        "document_id ani oznaceni jako Doklad: receipt. Uprednostni uzivatelsky srozumitelny nazev, "
        "odpovez pouze na polozenou otazku a necituj zdroje; aplikace je zobrazi samostatne."
    )


def _agent_decision_messages(history: list[dict], content: str, response_mode: str = "chat") -> list[dict]:
    recent_history = history[-6:]
    return [
        {
            "role": "system",
            "content": (
                "Jsi interní rozhodovací vrstva chatu nad osobními doklady. "
                "Vrať pouze validní JSON bez markdownu. "
                "Pokud lze odpovědět bez dokladů, vrať {\"action\":\"answer\",\"content\":\"...\"}. "
                "Pokud dotaz vyžaduje informace z dokladů, vrať "
                "{\"action\":\"search_documents\",\"search\":{\"rag_queries\":[\"...\"],"
                "\"structured\":{\"merchant\":null,\"item\":null,\"date\":{\"mode\":null,\"value\":null,\"value_to\":null},"
                "\"amount\":{\"mode\":null,\"value\":null,\"value_to\":null}}}}. "
                "Dotazy na nakupy, uctenky, faktury, ceny, polozky, obchod, datum nakupu, provozovnu, adresu nebo doklad "
                "vzdy vyzaduji search_documents, i kdyz se odpoved zda byt zrejma z historie chatu. "
                "Konkretní fakta z dokladu nikdy neodpovidej pouze z historie nebo pameti; nejdriv si vyzadej hledani, aby backend mohl pripojit zdroje. "
                "U navazujících dotazů použij historii pro vytvoření samostatných hledacích textů. "
                "Nevymýšlej údaje z dokladů bez výsledků hledání."
            ) + _speech_style_instruction(response_mode),
        },
        *recent_history,
        {"role": "user", "content": content},
    ]


def _rag_queries_from_command(command: dict, fallback: str) -> list[str]:
    search = command.get("search") if isinstance(command.get("search"), dict) else {}
    raw_queries = search.get("rag_queries") or search.get("queries") or []
    if isinstance(raw_queries, str):
        raw_queries = [raw_queries]
    queries = [query.strip() for query in raw_queries if isinstance(query, str) and query.strip()]
    return queries[:3] or [fallback]


def _structured_query_from_command(command: dict) -> str:
    search = command.get("search") if isinstance(command.get("search"), dict) else {}
    structured = search.get("structured") if isinstance(search.get("structured"), dict) else {}
    explicit = search.get("structured_query")
    parts = [explicit.strip()] if isinstance(explicit, str) and explicit.strip() else []
    for key in ("merchant", "item", "document_type", "invoice_number", "variable_symbol"):
        value = structured.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    for key in ("date", "amount"):
        nested = structured.get(key)
        if isinstance(nested, dict):
            for nested_key in ("value", "value_to"):
                value = nested.get(nested_key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
                elif isinstance(value, int | float):
                    parts.append(str(value))
    return " ".join(dict.fromkeys(parts))


async def _run_document_retrieval(
    session: AsyncSession,
    user_id: uuid.UUID,
    command: dict | None,
    fallback_query: str,
) -> tuple[list[dict], dict[str, object]]:
    if command is None:
        rag_chunks = await search_document_chunks(session, user_id, fallback_query)
        return rag_chunks, retrieval_metadata(used_rag=True, used_search=False, source_count=0)

    rag_queries = _rag_queries_from_command(command, fallback_query)
    structured_query = _structured_query_from_command(command)
    rag_results = []
    for query in rag_queries:
        rag_results.extend(await search_document_chunks(session, user_id, query))
    structured_results = await search_document_structured(session, user_id, structured_query) if structured_query else []
    chunks = _merge_chunks(structured_results, rag_results)
    return chunks, retrieval_metadata(
        used_rag=bool(rag_queries),
        used_search=bool(structured_query),
        source_count=0,
    )


def _final_messages(
    history: list[dict],
    content: str,
    rag_context: str,
    retrieval: dict[str, object],
    response_mode: str = "chat",
) -> list[dict]:
    system_content = (
        "Odpovidej přirozeně česky. "
        "Syrova UUID ani document_id nikdy neopisuj do textu odpovedi, pokud se na ne uzivatel primo nepta. "
        "Backend relevantni doklady zobrazi jako klikatelne zdroje pod odpovedi."
    )
    system_content += _speech_style_instruction(response_mode)
    if rag_context:
        system_content = (
            f"{rag_context}\n\n"
            "Odpovidej jen podle zdroju, ktere skutecne souvisi s dotazem; nesouvisejici doklady ignoruj. "
            + system_content
        )
    elif retrieval.get("mode") != "none":
        system_content = (
            "Vyhledavani v dokladech nevratilo zadny spolehlivy kontext. "
            "Pokud se uzivatel pta na doklady, rekni, ze v ulozenych dokladech nebyl nalezen relevantni zaznam. "
            + system_content
        )
    return [{"role": "system", "content": system_content}, *history, {"role": "user", "content": content}]


async def generate_chat_agent_response(
    *,
    session: AsyncSession,
    user_id: uuid.UUID,
    user_settings: UserSettings,
    history: list[dict],
    content: str,
    model: str,
    conversation_id: uuid.UUID | None = None,
    client: OllamaClient | None = None,
    response_mode: str = "chat",
) -> ChatAgentResult:
    llm_client = client or OllamaClient()
    logger.info(
        "agent decision start conversation_id=%s user_id=%s model=%s history_messages=%d user_message=%r",
        conversation_id,
        user_id,
        model,
        len(history),
        log_preview(content, 240),
    )
    decision_text = await llm_client.chat(
        _agent_decision_messages(history, content, response_mode),
        model=model,
    )
    logger.info(
        "agent decision raw conversation_id=%s response=%r",
        conversation_id,
        log_preview(decision_text),
    )
    decision = _parse_agent_command(decision_text)
    rag_chunks: list[dict] = []
    retrieval = retrieval_metadata(False, False, 0)

    if decision and decision.get("action") == "answer" and isinstance(decision.get("content"), str):
        logger.info("agent decision parsed conversation_id=%s action=answer", conversation_id)
        assistant_text = decision["content"]
        logger.info("agent direct answer conversation_id=%s response=%r", conversation_id, log_preview(assistant_text))
    else:
        search_command = decision if decision and decision.get("action") == "search_documents" else None
        if search_command:
            rag_queries_for_log = _rag_queries_from_command(search_command, content)
            structured_query_for_log = _structured_query_from_command(search_command)
            logger.info(
                "agent decision parsed conversation_id=%s action=search_documents rag_queries=%s structured_query=%r",
                conversation_id,
                rag_queries_for_log,
                structured_query_for_log,
            )
        else:
            logger.info(
                "agent decision fallback conversation_id=%s reason=invalid_or_missing_json fallback_query=%r",
                conversation_id,
                log_preview(content, 240),
            )
        rag_chunks, retrieval = await _run_document_retrieval(session, user_id, search_command, content)
        rag_chunks, used_reranker = await rerank_document_chunks(session, content, rag_chunks)
        retrieval["used_reranker"] = used_reranker
        retrieval["reranker_model"] = next(
            (chunk.get("reranker_model") for chunk in rag_chunks if chunk.get("reranker_model")),
            None,
        ) if used_reranker else None
        sources = sources_from_chunks(rag_chunks, user_settings)
        retrieval["source_count"] = len(sources)
        logger.info(
            "agent retrieval finished conversation_id=%s mode=%s used_rag=%s used_search=%s chunks=%d sources=%d",
            conversation_id,
            retrieval["mode"],
            retrieval["used_rag"],
            retrieval["used_search"],
            len(rag_chunks),
            len(sources),
        )
        relevant_chunks = select_source_chunks(rag_chunks, user_settings)
        if relevant_chunks:
            rag_context = build_chat_context(relevant_chunks)
            assistant_text = await llm_client.chat(
                _final_messages(history, content, rag_context, retrieval, response_mode),
                model=model,
            )
            logger.info("agent final answer conversation_id=%s response=%r", conversation_id, log_preview(assistant_text))
        else:
            assistant_text = "V uložených dokladech jsem k tomuto dotazu nenašel relevantní záznam."
            logger.info("agent no-source answer conversation_id=%s", conversation_id)

    sources = [] if not rag_chunks else sources_from_chunks(rag_chunks, user_settings)
    retrieval["source_count"] = len(sources)
    return ChatAgentResult(content=assistant_text, sources=sources, retrieval=retrieval, model=model)
