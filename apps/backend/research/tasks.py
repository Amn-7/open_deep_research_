import asyncio
import json
import os
import re
import uuid
from datetime import timedelta
from decimal import Decimal

import fitz
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from langchain.chat_models import init_chat_model
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from open_deep_research.deep_researcher import deep_researcher
from open_deep_research.utils import get_api_key_for_model

from .models import (
    ResearchSession,
    ResearchReport,
    ResearchSummary,
    ResearchReasoning,
    ResearchCost,
    UploadedDocument,
)


# --- Token tracking (best-effort, model/provider dependent) ---
class TokenUsageCallback(BaseCallbackHandler):
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0

    def on_llm_end(self, response, **kwargs):
        usage = {}

        # Many LangChain chat models attach usage here
        llm_output = getattr(response, "llm_output", None) or {}
        if isinstance(llm_output, dict):
            usage = llm_output.get("token_usage") or llm_output.get("usage") or {}

        # Normalize common shapes
        # OpenAI style: {"prompt_tokens": x, "completion_tokens": y}
        if "prompt_tokens" in usage or "completion_tokens" in usage:
            self.input_tokens += int(usage.get("prompt_tokens", 0) or 0)
            self.output_tokens += int(usage.get("completion_tokens", 0) or 0)
            return

        # Anthropic style often: {"input_tokens": x, "output_tokens": y}
        if "input_tokens" in usage or "output_tokens" in usage:
            self.input_tokens += int(usage.get("input_tokens", 0) or 0)
            self.output_tokens += int(usage.get("output_tokens", 0) or 0)
            return


def _load_model_pricing() -> dict[str, tuple[Decimal, Decimal]]:
    raw = os.environ.get("ODR_MODEL_COSTS_JSON", "").strip()
    if not raw:
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    pricing: dict[str, tuple[Decimal, Decimal]] = {}
    for model_name, rates in data.items():
        in_rate = None
        out_rate = None

        if isinstance(rates, dict):
            in_rate = rates.get("input") or rates.get("in")
            out_rate = rates.get("output") or rates.get("out")
        elif isinstance(rates, (list, tuple)) and len(rates) >= 2:
            in_rate, out_rate = rates[0], rates[1]

        if in_rate is None or out_rate is None:
            continue

        try:
            pricing[str(model_name)] = (Decimal(str(in_rate)), Decimal(str(out_rate)))
        except Exception:
            continue

    return pricing


def _estimate_cost_usd(model_name: str, in_tokens: int, out_tokens: int) -> Decimal:
    """
    Cost estimator using env-supplied pricing map (per 1K tokens).
    """
    pricing = _load_model_pricing()
    if not pricing:
        return Decimal("0")

    if model_name not in pricing and "default" in pricing:
        model_name = "default"

    if model_name not in pricing:
        return Decimal("0")

    in_rate, out_rate = pricing[model_name]
    return (Decimal(in_tokens) / Decimal(1000) * in_rate) + (Decimal(out_tokens) / Decimal(1000) * out_rate)


def _extract_text_from_pdf(path: str) -> str:
    text_parts = []
    with fitz.open(path) as doc:
        for page in doc:
            text_parts.append(page.get_text("text"))
    return "\n".join(text_parts)


def _extract_text_from_txt(path: str) -> str:
    with open(path, "rb") as handle:
        raw = handle.read()
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def _summarize_text(
    text: str,
    model_name: str,
    max_tokens: int,
    prompt: str,
    token_cb: BaseCallbackHandler | None = None,
) -> str:
    if not text or not model_name:
        return ""

    api_key = get_api_key_for_model(model_name, RunnableConfig())
    model = init_chat_model(
        model=model_name,
        max_tokens=max_tokens,
        api_key=api_key,
    )

    config = {"callbacks": [token_cb]} if token_cb else None

    async def _run():
        return await model.ainvoke([HumanMessage(content=prompt + text)], config=config)

    try:
        response = asyncio.run(_run())
    except Exception:
        return ""

    content = getattr(response, "content", "")
    return content.strip() if content else ""


def _extract_sources_from_report(report_text: str) -> list[dict]:
    if not report_text:
        return []

    lower = report_text.lower()
    idx = lower.rfind("sources")
    if idx == -1:
        return []

    section = report_text[idx:].splitlines()
    sources = []
    for line in section:
        line = line.strip()
        if not line:
            continue
        line = line.lstrip("-* ").strip()
        match = re.match(r"^\[(\d+)\]\s*(.+)$", line)
        if not match:
            match = re.match(r"^(\d+)[\.\)]\s*(.+)$", line)
        if not match:
            continue
        source_id = match.group(1)
        rest = match.group(2).strip()
        url_match = re.search(r"(https?://\S+)", rest)
        url = url_match.group(1).rstrip(").,]>") if url_match else ""
        sources.append(
            {
                "id": int(source_id),
                "citation": rest,
                "url": url,
            }
        )
    return sources


@shared_task
def ping_task(session_id: str):
    # keep this around as a simple health check
    ResearchSession.objects.filter(id=session_id).update(status=ResearchSession.Status.RUNNING)
    return "ok"


@shared_task
def process_uploaded_document(document_id: str):
    doc = UploadedDocument.objects.select_related("session").filter(id=document_id).first()
    if not doc:
        return "document not found"

    path = doc.file.path
    ext = os.path.splitext(doc.filename or path)[1].lower()

    try:
        if ext == ".pdf":
            extracted = _extract_text_from_pdf(path)
        elif ext == ".txt":
            extracted = _extract_text_from_txt(path)
        else:
            extracted = ""
    except Exception as exc:
        doc.extracted_text = ""
        doc.extracted_summary = f"Extraction failed: {type(exc).__name__}"
        doc.save(update_fields=["extracted_text", "extracted_summary"])
        return "failed"

    extracted = extracted.strip()
    if not extracted:
        doc.extracted_text = ""
        doc.extracted_summary = ""
        doc.save(update_fields=["extracted_text", "extracted_summary"])
        return "empty"

    store_limit = int(os.environ.get("ODR_UPLOAD_STORE_MAX_CHARS", "50000"))
    summary_limit = int(os.environ.get("ODR_UPLOAD_MAX_CHARS", "20000"))
    summary_model = os.environ.get("ODR_UPLOAD_SUMMARY_MODEL") or os.environ.get("ODR_COMPRESSION_MODEL") or ""
    summary_max_tokens = int(os.environ.get("ODR_UPLOAD_SUMMARY_MAX_TOKENS", "400"))

    stored_text = extracted[:store_limit]

    summary_prompt = (
        "Summarize the following document for research context. "
        "Return 5-10 concise bullet points with key facts, entities, and numbers.\n\n"
        "Document:\n"
    )

    summary_text = _summarize_text(
        extracted[:summary_limit],
        summary_model,
        summary_max_tokens,
        summary_prompt,
    )

    if not summary_text:
        summary_text = stored_text[:1500].strip()

    doc.extracted_text = stored_text
    doc.extracted_summary = summary_text
    doc.save(update_fields=["extracted_text", "extracted_summary"])

    return "processed"


@shared_task
def run_research(session_id: str):
    session = ResearchSession.objects.select_related("parent").filter(id=session_id).first()
    if not session:
        return "session not found"

    pending_docs = UploadedDocument.objects.filter(
        session=session, extracted_summary="", extracted_text=""
    ).order_by("created_at")
    if pending_docs.exists():
        oldest = pending_docs.first()
        wait_window = int(os.environ.get("ODR_UPLOAD_WAIT_SECONDS", "120"))
        if oldest and timezone.now() - oldest.created_at < timedelta(seconds=wait_window):
            run_research.apply_async(args=[session_id], countdown=15)
            return "waiting for documents"

    # Mark running after document processing window
    ResearchSession.objects.filter(id=session_id).update(status=ResearchSession.Status.RUNNING)

    # Build context to avoid repetition
    parent_summary = ""
    if session.parent_id and hasattr(session.parent, "summary"):
        parent_summary = session.parent.summary.summary or ""

    doc_summaries = list(
        UploadedDocument.objects.filter(session=session).values_list("extracted_summary", flat=True)
    )
    doc_summaries = [s for s in doc_summaries if s]

    context_blocks = []
    if parent_summary:
        context_blocks.append(
            "Previous research summary (DO NOT repeat this; focus on new info / updates / gaps):\n"
            + parent_summary
        )
    if doc_summaries:
        context_blocks.append(
            "User-provided documents (use this as additional context):\n"
            + "\n\n---\n\n".join(doc_summaries)
        )

    user_content = session.original_query.strip()
    if context_blocks:
        user_content = user_content + "\n\n" + "\n\n".join(context_blocks)

    # LangSmith trace/run id (store as trace_id)
    trace_id = str(uuid.uuid4())

    # Config-driven controls (env)
    # NOTE: open_deep_research reads model keys internally based on model names.
    configurable = {
        # safest default if you haven't configured paid APIs yet:
        "search_api": os.environ.get("ODR_SEARCH_API", "none"),
        # models are optional if the repo has defaults; set them via env for clarity:
        "research_model": os.environ.get("ODR_RESEARCH_MODEL", ""),
        "compression_model": os.environ.get("ODR_COMPRESSION_MODEL", ""),
        "final_report_model": os.environ.get("ODR_FINAL_REPORT_MODEL")
        or os.environ.get("ODR_WRITER_MODEL", ""),
        "summarization_model": os.environ.get("ODR_SUMMARIZATION_MODEL")
        or os.environ.get("ODR_COMPRESSION_MODEL", ""),
        "allow_clarification": False,  # your API is async; don’t block on clarification
    }

    # Remove empty config values so defaults still work
    configurable = {k: v for k, v in configurable.items() if v not in ("", None)}

    token_cb = TokenUsageCallback()

    config = RunnableConfig(
        configurable=configurable,
        callbacks=[token_cb],
        run_id=trace_id,  # This becomes the LangChain/LangSmith run id
        tags=["django", "celery", "open_deep_research"],
    )

    try:
        # Run the LangGraph async workflow inside Celery
        final_state = asyncio.run(
            deep_researcher.ainvoke(
                {"messages": [HumanMessage(content=user_content)]},
                config=config,
            )
        )

        # Best-effort extraction (key names can vary)
        report_text = (
            final_state.get("final_report")
            or final_state.get("report")
            or final_state.get("output")
            or ""
        )

        sources = final_state.get("sources") or final_state.get("citations") or []
        if not sources:
            sources = _extract_sources_from_report(report_text)

        summary_model = (
            os.environ.get("ODR_REPORT_SUMMARY_MODEL")
            or configurable.get("compression_model")
            or configurable.get("final_report_model")
            or ""
        )
        summary_max_tokens = int(os.environ.get("ODR_REPORT_SUMMARY_MAX_TOKENS", "350"))
        summary_char_limit = int(os.environ.get("ODR_REPORT_SUMMARY_MAX_CHARS", "12000"))
        summary_prompt = (
            "Summarize the research report in 5-10 bullet points. "
            "Focus on key findings, numbers, and conclusions. "
            "Do not include chain-of-thought.\n\nReport:\n"
        )
        summary_text = _summarize_text(
            report_text[:summary_char_limit],
            summary_model,
            summary_max_tokens,
            summary_prompt,
            token_cb=token_cb,
        )
        if not summary_text:
            summary_text = report_text[:1200].strip()

        research_brief = (final_state.get("research_brief") or "").strip()
        if len(research_brief) > 500:
            research_brief = research_brief[:500] + "..."

        reasoning_lines = [
            "High-level reasoning:",
            "- Used open_deep_research LangGraph workflow (clarify → brief → supervisor → final report).",
            f"- Search API: {configurable.get('search_api', 'default')}.",
        ]
        if research_brief:
            reasoning_lines.append(f"- Planning: derived brief -> {research_brief}")
        else:
            reasoning_lines.append("- Planning: derived a focused brief from the query.")
        if sources:
            reasoning_lines.append(f"- Source selection: kept {len(sources)} sources for citations.")
        else:
            reasoning_lines.append("- Source selection: kept the most relevant sources.")
        if parent_summary:
            reasoning_lines.append("- Continuation: used prior summary to avoid repeating topics.")
        if doc_summaries:
            reasoning_lines.append(f"- User documents: incorporated {len(doc_summaries)} uploaded summaries.")

        reasoning_text = "\n".join(reasoning_lines)

        cost_model_name = (
            os.environ.get("ODR_COST_MODEL")
            or configurable.get("final_report_model")
            or configurable.get("research_model")
            or configurable.get("compression_model")
            or ""
        )

        in_tokens = int(token_cb.input_tokens)
        out_tokens = int(token_cb.output_tokens)
        total_tokens = in_tokens + out_tokens
        est_cost = _estimate_cost_usd(cost_model_name, in_tokens, out_tokens)

        with transaction.atomic():
            # trace id on session
            session.trace_id = trace_id
            session.status = ResearchSession.Status.COMPLETED
            session.save(update_fields=["trace_id", "status", "updated_at"])

            ResearchReport.objects.update_or_create(
                session=session,
                defaults={"report": report_text, "sources": sources},
            )

            ResearchSummary.objects.update_or_create(
                session=session,
                defaults={"summary": summary_text},
            )

            ResearchReasoning.objects.update_or_create(
                session=session,
                defaults={"reasoning": reasoning_text},
            )

            ResearchCost.objects.update_or_create(
                session=session,
                defaults={
                    "input_tokens": in_tokens,
                    "output_tokens": out_tokens,
                    "total_tokens": total_tokens,
                    "estimated_cost_usd": est_cost,
                    "model_name": cost_model_name,
                },
            )

        return "completed"

    except Exception as e:
        # Mark failed and store basic failure info (no chain-of-thought)
        with transaction.atomic():
            session.status = ResearchSession.Status.FAILED
            session.trace_id = trace_id
            session.save(update_fields=["status", "trace_id", "updated_at"])

            ResearchReasoning.objects.update_or_create(
                session=session,
                defaults={"reasoning": f"Run failed: {type(e).__name__}: {str(e)}"},
            )

        return f"failed: {type(e).__name__}"
